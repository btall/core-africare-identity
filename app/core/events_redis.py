"""
SDK Redis pur pour messaging Phase 1 MVP - core-africare-identity.

Architecture :
- Redis Pub/Sub pour événements temps réel
- Pas de persistence garantie (acceptable Phase 1, volume <1000 msg/jour)
- Migration vers Azure Service Bus en Phase 2

Usage:
    from app.core.events import publish, subscribe

    @subscribe("user.created")
    async def handle_user_created(payload: dict):
        print(f"User created: {payload}")

    await publish("user.created", {"user_id": "123"})
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import redis.asyncio as redis
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Client Redis global (créé au démarrage, réutilisé)
redis_client: redis.Redis | None = None

# Registre des handlers
handlers: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}

# Task de consommation
consumer_task: asyncio.Task | None = None


async def init_redis():
    """Initialise le client Redis au démarrage."""
    global redis_client
    redis_client = redis.from_url(
        settings.REDIS_URL,
        db=settings.REDIS_DB,
        decode_responses=True,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
    )
    # Test connexion
    await redis_client.ping()
    logger.info(f"Redis client initialisé: {settings.REDIS_URL}")


async def close_redis():
    """Ferme le client Redis proprement."""
    global redis_client
    if redis_client:
        await redis_client.close()
        logger.info("Redis client fermé")


async def publish(subject: str, payload: dict | BaseModel, max_retries: int = 3):
    """
    Publie un événement via Redis Pub/Sub.

    Args:
        subject: Sujet de l'événement (ex: "user.created")
        payload: Données de l'événement (dict ou Pydantic model)
        max_retries: Nombre maximum de tentatives (défaut: 3)

    Raises:
        Exception: Si toutes les tentatives échouent

    Note Phase 1:
        - Pas de persistence garantie (Redis Pub/Sub)
        - Si aucun subscriber, message perdu
        - Migration Service Bus Phase 2 pour garanties
    """
    # Préparer le payload
    if isinstance(payload, BaseModel):
        payload_dict = payload.model_dump(mode="json")
    else:
        payload_dict = payload

    message_id = str(uuid.uuid4())

    # Message avec métadonnées
    event_data = {
        "id": message_id,
        "subject": subject,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": payload_dict,
    }

    # Telemetry
    span_attributes = {
        "messaging.system": "redis",
        "messaging.destination": subject,
        "messaging.message.id": message_id,
    }

    with tracer.start_as_current_span(
        f"publish.{subject}", kind=trace.SpanKind.PRODUCER, attributes=span_attributes
    ) as span:
        # Retry avec backoff exponentiel
        last_exception = None
        for attempt in range(max_retries):
            try:
                # Publier via Redis Pub/Sub
                await redis_client.publish(subject, json.dumps(event_data))

                logger.debug(f"Événement '{subject}' publié avec ID: {message_id}")
                span.add_event("Événement publié avec succès", {"attempt": attempt + 1})
                return  # Succès

            except Exception as e:
                last_exception = e
                wait_time = 2**attempt  # Backoff: 1s, 2s, 4s

                if attempt < max_retries - 1:
                    logger.warning(
                        f"Échec publication '{subject}' (tentative {attempt + 1}/{max_retries}): {e}. "
                        f"Retry dans {wait_time}s"
                    )
                    span.add_event(
                        f"Retry après échec (tentative {attempt + 1})",
                        {"error": str(e), "wait_time": wait_time},
                    )
                    await asyncio.sleep(wait_time)
                else:
                    # Dernière tentative échouée
                    error_msg = f"Échec définitif publication '{subject}' après {max_retries} tentatives: {e}"
                    logger.error(error_msg, exc_info=True)
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    span.record_exception(e)
                    raise last_exception


def subscribe(subject: str):
    """Décorateur pour enregistrer un handler."""

    def decorator(func: Callable[[dict], Awaitable[None]]) -> Callable[[dict], Awaitable[None]]:
        if subject not in handlers:
            handlers[subject] = []
        handlers[subject].append(func)
        logger.info(f"Handler '{func.__name__}' enregistré pour '{subject}'")
        return func

    return decorator


async def consume_messages():
    """
    Boucle de consommation Redis Pub/Sub.

    S'abonne à tous les subjects enregistrés via @subscribe() et
    exécute les handlers correspondants.
    """
    pubsub = redis_client.pubsub()

    # S'abonner à tous les subjects enregistrés
    if not handlers:
        logger.warning("Aucun handler enregistré, consommation Redis inactive")
        return

    for subject in handlers.keys():
        await pubsub.subscribe(subject)
        logger.info(f"Abonné au sujet Redis: {subject}")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                subject = message["channel"]

                try:
                    event_data = json.loads(message["data"])
                    payload = event_data.get("data", {})
                    message_id = event_data.get("id")

                    # Telemetry
                    span_attributes = {
                        "messaging.system": "redis",
                        "messaging.destination": subject,
                        "messaging.message.id": message_id,
                    }

                    with tracer.start_as_current_span(
                        f"consume.{subject}",
                        kind=trace.SpanKind.CONSUMER,
                        attributes=span_attributes,
                    ) as span:
                        # Exécuter les handlers
                        subject_handlers = handlers.get(subject, [])

                        handlers_executed = 0
                        handlers_failed = 0
                        for handler in subject_handlers:
                            try:
                                await handler(payload)
                                handlers_executed += 1
                                logger.debug(
                                    f"Handler '{handler.__name__}' exécuté pour '{subject}'"
                                )
                            except Exception as e:
                                handlers_failed += 1
                                logger.error(
                                    f"Erreur handler '{handler.__name__}' pour '{subject}': {e}",
                                    exc_info=True,
                                )
                                span.record_exception(e)

                        span.set_attributes(
                            {
                                "handlers.executed": handlers_executed,
                                "handlers.failed": handlers_failed,
                            }
                        )

                except json.JSONDecodeError as e:
                    logger.error(f"Erreur décodage JSON pour '{subject}': {e}")
                except Exception as e:
                    logger.error(f"Erreur traitement événement '{subject}': {e}", exc_info=True)

    except asyncio.CancelledError:
        logger.info("Consommation Redis annulée")
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()


async def start_consuming():
    """Démarre la consommation d'événements Redis."""
    global consumer_task

    if not handlers:
        logger.warning("Aucun handler enregistré, consommation Redis non démarrée")
        return

    consumer_task = asyncio.create_task(consume_messages(), name="redis_consumer")
    logger.info(f"Consommation Redis démarrée pour {len(handlers)} subject(s)")


async def stop_consuming():
    """Arrête la consommation d'événements Redis."""
    global consumer_task

    if consumer_task and not consumer_task.done():
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        logger.info("Consommation Redis arrêtée")


# Lifespan pour FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestionnaire de cycle de vie FastAPI pour Redis."""
    # Startup
    await init_redis()
    await start_consuming()
    logger.info(f"Redis messaging initialisé (URL: {settings.REDIS_URL})")

    yield

    # Shutdown
    await stop_consuming()
    await close_redis()
    logger.info("Redis messaging arrêté proprement")


# Compatibilité
async def get_publisher():
    """Retourne la fonction publish pour injection de dépendance."""
    return publish


__all__ = ["get_publisher", "lifespan", "publish", "subscribe"]
