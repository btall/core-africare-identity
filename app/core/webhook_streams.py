"""
Système de webhook résilient avec Redis Streams.

Ce module implémente un système de persistence et retry pour les webhooks Keycloak
en utilisant Redis Streams. Contrairement à Redis Pub/Sub, Redis Streams garantit
la persistence des messages et permet des retries automatiques en cas d'échec.

Architecture:
    Keycloak Webhook → XADD Redis Stream → Return 200 OK
                              ↓
                    Background Worker (XREADGROUP)
                              ↓
                    Process + Sync PostgreSQL
                              ↓
                    XACK (acknowledge) ou Retry

Avantages vs Pub/Sub:
    - Persistence: Messages survient aux redémarrages
    - Consumer groups: Plusieurs workers possibles
    - Acknowledgement: XACK après traitement réussi
    - Retry automatique: Messages non-ACK sont reconsommés
    - Monitoring: XPENDING pour voir messages en cours
    - Idempotence: Message IDs uniques

Usage:
    # Producer (webhook endpoint)
    from app.core.webhook_streams import add_webhook_event
    await add_webhook_event(event)

    # Consumer (background worker)
    from app.core.webhook_streams import consume_webhook_events
    asyncio.create_task(consume_webhook_events())
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import redis.asyncio as redis
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.schemas.keycloak import KeycloakWebhookEvent, SyncResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Configuration Redis Streams
WEBHOOK_STREAM_NAME = "keycloak:webhooks"
WEBHOOK_CONSUMER_GROUP = "core-africare-identity-workers"
WEBHOOK_CONSUMER_NAME = "worker-1"  # Peut être dynamique avec hostname/pod ID

# Paramètres de retry
MAX_DELIVERY_ATTEMPTS = 5  # Nombre max de tentatives
RETRY_BACKOFF_MS = 5000  # 5 secondes entre retries
CLAIM_IDLE_TIME_MS = 60000  # 1 minute avant reclaim des messages pending

# Client Redis global (réutilisé depuis events_redis)
webhook_redis_client: redis.Redis | None = None

# Task de consommation
webhook_consumer_task: asyncio.Task | None = None

# Handler registry (modifié pour accepter event complet)
webhook_handler: Callable[[AsyncSession, KeycloakWebhookEvent], Awaitable[SyncResult]] | None = None


async def init_webhook_redis():
    """
    Initialise le client Redis et crée le consumer group si nécessaire.

    Le consumer group permet à plusieurs workers de consommer en parallèle
    avec distribution automatique des messages.
    """
    global webhook_redis_client

    webhook_redis_client = redis.from_url(
        settings.REDIS_URL,
        db=settings.REDIS_DB,
        decode_responses=True,
        socket_timeout=10.0,
        socket_connect_timeout=10.0,
    )

    # Test connexion
    await webhook_redis_client.ping()
    logger.info(f"Webhook Redis client initialisé: {settings.REDIS_URL}")

    # Créer le consumer group (ignore si existe déjà)
    try:
        await webhook_redis_client.xgroup_create(
            WEBHOOK_STREAM_NAME, WEBHOOK_CONSUMER_GROUP, id="0", mkstream=True
        )
        logger.info(
            f"Consumer group créé: {WEBHOOK_CONSUMER_GROUP} sur stream {WEBHOOK_STREAM_NAME}"
        )
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"Consumer group déjà existant: {WEBHOOK_CONSUMER_GROUP}")
        else:
            raise


async def close_webhook_redis():
    """Ferme le client Redis proprement."""
    global webhook_redis_client
    if webhook_redis_client:
        await webhook_redis_client.close()
        logger.info("Webhook Redis client fermé")


async def add_webhook_event(event: KeycloakWebhookEvent) -> str:
    """
    Ajoute un événement webhook au Redis Stream (producer).

    Cette fonction est appelée par l'endpoint webhook pour persister
    l'événement immédiatement et retourner 200 OK à Keycloak.

    Args:
        event: Événement webhook Keycloak validé par Pydantic

    Returns:
        str: Message ID généré par Redis (format: timestamp-sequence)

    Raises:
        Exception: Si échec d'ajout au stream (très rare)

    Example:
        >>> event = KeycloakWebhookEvent(...)
        >>> message_id = await add_webhook_event(event)
        >>> print(f"Event persisted: {message_id}")
        Event persisted: 1234567890123-0
    """
    span_attributes = {
        "messaging.system": "redis-streams",
        "messaging.destination": WEBHOOK_STREAM_NAME,
        "event.type": event.event_type,
        "event.user_id": event.user_id,
    }

    with tracer.start_as_current_span(
        "add_webhook_event", kind=trace.SpanKind.PRODUCER, attributes=span_attributes
    ) as span:
        try:
            # Sérialiser l'événement
            event_data = {
                "event_type": event.event_type,
                "user_id": event.user_id,
                "realm_id": event.realm_id,
                "timestamp": event.timestamp,
                "payload": event.model_dump_json(exclude_none=True),
                "added_at": datetime.now(UTC).isoformat(),
                "delivery_attempts": "0",  # Compteur de tentatives
            }

            # XADD: Ajoute au stream avec ID auto-généré
            message_id = await webhook_redis_client.xadd(WEBHOOK_STREAM_NAME, event_data)

            logger.info(
                f"Webhook event ajouté au stream: type={event.event_type}, "
                f"user_id={event.user_id}, message_id={message_id}"
            )

            span.set_attribute("messaging.message.id", message_id)
            span.add_event("Event ajouté au stream avec succès")

            return message_id

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            logger.error(f"Erreur lors de l'ajout au stream: {e}", exc_info=True)
            raise


def register_webhook_handler(
    handler: Callable[[AsyncSession, KeycloakWebhookEvent], Awaitable[SyncResult]],
):
    """
    Enregistre le handler qui traitera les webhooks.

    Le handler doit accepter (db: AsyncSession, event: KeycloakWebhookEvent)
    et retourner SyncResult.

    Args:
        handler: Fonction async qui traite l'événement

    Example:
        >>> async def process_webhook(db: AsyncSession, event: KeycloakWebhookEvent):
        ...     # Traiter l'événement
        ...     return SyncResult(success=True, ...)
        >>> register_webhook_handler(process_webhook)
    """
    global webhook_handler
    webhook_handler = handler
    logger.info(f"Handler webhook enregistré: {handler.__name__}")


async def consume_webhook_events():
    """
    Boucle de consommation des événements webhook (consumer).

    Utilise XREADGROUP pour:
    - Lire les nouveaux messages
    - Récupérer les messages pending (non-ACK)
    - Traiter avec le handler enregistré
    - XACK si succès, sinon retry

    Cette fonction tourne en background et ne se termine qu'au shutdown.
    """
    if not webhook_handler:
        logger.error("Aucun handler webhook enregistré, consommation impossible")
        return

    logger.info(
        f"Démarrage consommation webhook stream: {WEBHOOK_STREAM_NAME} "
        f"(group: {WEBHOOK_CONSUMER_GROUP}, consumer: {WEBHOOK_CONSUMER_NAME})"
    )

    try:
        while True:
            try:
                # 1. Lire les nouveaux messages (block 1 seconde)
                messages = await webhook_redis_client.xreadgroup(
                    WEBHOOK_CONSUMER_GROUP,
                    WEBHOOK_CONSUMER_NAME,
                    {WEBHOOK_STREAM_NAME: ">"},  # > = nouveaux messages seulement
                    count=10,  # Batch de 10 messages max
                    block=1000,  # Block 1s si aucun message
                )

                if messages:
                    for _stream_name, stream_messages in messages:
                        for message_id, message_data in stream_messages:
                            await _process_webhook_message(message_id, message_data)

                # 2. Récupérer les messages pending (retries)
                await _reclaim_pending_messages()

            except asyncio.CancelledError:
                logger.info("Consommation webhook annulée (shutdown)")
                raise

            except Exception as e:
                logger.error(f"Erreur dans la boucle de consommation: {e}", exc_info=True)
                # Attendre avant retry pour éviter la boucle infinie
                await asyncio.sleep(5)

    except asyncio.CancelledError:
        logger.info("Consumer webhook arrêté proprement")


async def _process_webhook_message(message_id: str, message_data: dict):
    """
    Traite un message webhook individuel.

    Args:
        message_id: ID du message Redis (format: timestamp-sequence)
        message_data: Données du message (event sérialisé)
    """
    span_attributes = {
        "messaging.system": "redis-streams",
        "messaging.destination": WEBHOOK_STREAM_NAME,
        "messaging.message.id": message_id,
        "event.type": message_data.get("event_type"),
    }

    with tracer.start_as_current_span(
        "process_webhook_message", kind=trace.SpanKind.CONSUMER, attributes=span_attributes
    ) as span:
        try:
            # Incrémenter le compteur de tentatives
            delivery_attempts = int(message_data.get("delivery_attempts", 0)) + 1

            logger.info(
                f"Traitement webhook message: id={message_id}, "
                f"type={message_data.get('event_type')}, "
                f"attempt={delivery_attempts}"
            )

            # Vérifier le nombre max de tentatives
            if delivery_attempts > MAX_DELIVERY_ATTEMPTS:
                logger.error(
                    f"Message {message_id} abandonné après {MAX_DELIVERY_ATTEMPTS} tentatives"
                )
                await _move_to_dead_letter(message_id, message_data)
                # ACK pour retirer du stream
                await webhook_redis_client.xack(
                    WEBHOOK_STREAM_NAME, WEBHOOK_CONSUMER_GROUP, message_id
                )
                return

            # Désérialiser l'événement
            event = KeycloakWebhookEvent.model_validate_json(message_data["payload"])

            # Créer une session DB pour le traitement
            async with async_session_maker() as db:
                # Appeler le handler
                result = await webhook_handler(db, event)

                if result.success:
                    # Succès: ACK le message
                    await webhook_redis_client.xack(
                        WEBHOOK_STREAM_NAME, WEBHOOK_CONSUMER_GROUP, message_id
                    )

                    logger.info(
                        f"Webhook traité avec succès: id={message_id}, "
                        f"type={event.event_type}, message={result.message}"
                    )

                    span.add_event("Webhook traité avec succès")

                else:
                    # Échec mais pas d'exception: laisser pending pour retry
                    logger.warning(
                        f"Webhook traité avec échec (retry): id={message_id}, "
                        f"message={result.message}"
                    )

                    # Mettre à jour le compteur de tentatives
                    # Note: On ne peut pas modifier un message dans Redis Streams,
                    # on se fie au système XPENDING pour le retry

                    span.add_event("Webhook traité avec échec, retry programmé")

        except Exception as e:
            # Exception non gérée: laisser pending pour retry
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))

            logger.error(f"Erreur lors du traitement webhook {message_id}: {e}", exc_info=True)

            # Le message reste dans pending, sera reclaim plus tard


async def _reclaim_pending_messages():
    """
    Récupère les messages pending qui n'ont pas été ACK depuis trop longtemps.

    Utilise XPENDING et XCLAIM pour récupérer les messages bloqués
    (crash du worker, timeout, etc.) et les réassigner au consumer actuel.
    """
    try:
        # Lister les messages pending (limite à 10 pour éviter surcharge)
        pending = await webhook_redis_client.xpending_range(
            WEBHOOK_STREAM_NAME,
            WEBHOOK_CONSUMER_GROUP,
            min="-",
            max="+",
            count=10,
            consumername=WEBHOOK_CONSUMER_NAME,
        )

        if not pending:
            return

        for info in pending:
            message_id = info["message_id"]
            idle_time_ms = info["time_since_delivered"]

            # Si le message est idle depuis trop longtemps, le reclaim
            if idle_time_ms > CLAIM_IDLE_TIME_MS:
                logger.warning(f"Reclaim pending message: id={message_id}, idle={idle_time_ms}ms")

                # XCLAIM: Réassigner le message à ce consumer
                claimed = await webhook_redis_client.xclaim(
                    WEBHOOK_STREAM_NAME,
                    WEBHOOK_CONSUMER_GROUP,
                    WEBHOOK_CONSUMER_NAME,
                    min_idle_time=CLAIM_IDLE_TIME_MS,
                    message_ids=[message_id],
                )

                # Retraiter les messages réclamés
                for claimed_message_id, claimed_data in claimed:
                    await _process_webhook_message(claimed_message_id, claimed_data)

    except Exception as e:
        logger.error(f"Erreur lors du reclaim des messages pending: {e}", exc_info=True)


async def _move_to_dead_letter(message_id: str, message_data: dict):
    """
    Déplace un message vers le stream dead-letter après échecs répétés.

    Args:
        message_id: ID du message original
        message_data: Données du message
    """
    dead_letter_stream = f"{WEBHOOK_STREAM_NAME}:dlq"

    try:
        # Ajouter métadonnées d'échec
        dlq_data = {
            **message_data,
            "original_message_id": message_id,
            "failed_at": datetime.now(UTC).isoformat(),
            "reason": f"Max delivery attempts ({MAX_DELIVERY_ATTEMPTS}) exceeded",
        }

        dlq_id = await webhook_redis_client.xadd(dead_letter_stream, dlq_data)

        logger.error(
            f"Message déplacé vers DLQ: original_id={message_id}, "
            f"dlq_id={dlq_id}, type={message_data.get('event_type')}"
        )

    except Exception as e:
        logger.error(f"Erreur lors du déplacement vers DLQ: {e}", exc_info=True)


async def start_webhook_consumer():
    """Démarre la consommation des webhooks en background."""
    global webhook_consumer_task

    if not webhook_handler:
        logger.warning(
            "Aucun handler webhook enregistré, consommation non démarrée. "
            "Utilisez register_webhook_handler() d'abord."
        )
        return

    webhook_consumer_task = asyncio.create_task(consume_webhook_events(), name="webhook_consumer")
    logger.info("Webhook consumer démarré en background")


async def stop_webhook_consumer():
    """Arrête la consommation des webhooks proprement."""
    global webhook_consumer_task

    if webhook_consumer_task and not webhook_consumer_task.done():
        webhook_consumer_task.cancel()
        try:
            await webhook_consumer_task
        except asyncio.CancelledError:
            pass
        logger.info("Webhook consumer arrêté")


__all__ = [
    "add_webhook_event",
    "close_webhook_redis",
    "consume_webhook_events",
    "init_webhook_redis",
    "register_webhook_handler",
    "start_webhook_consumer",
    "stop_webhook_consumer",
]
