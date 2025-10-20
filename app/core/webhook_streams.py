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
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import redis.asyncio as redis
from opentelemetry import metrics, trace
from opentelemetry.trace import Status, StatusCode
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.schemas.keycloak import KeycloakWebhookEvent, SyncResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

# OpenTelemetry Metrics pour monitoring
webhook_events_produced = meter.create_counter(
    "webhook.events.produced",
    description="Nombre total d'événements webhook persistés dans Redis Streams (XADD)",
    unit="events",
)

webhook_events_consumed = meter.create_counter(
    "webhook.events.consumed",
    description="Nombre total d'événements webhook consommés depuis Redis Streams (XREADGROUP)",
    unit="events",
)

webhook_events_acked = meter.create_counter(
    "webhook.events.acked",
    description="Nombre total d'événements webhook traités avec succès (XACK)",
    unit="events",
)

webhook_events_failed = meter.create_counter(
    "webhook.events.failed",
    description="Nombre total d'événements webhook en échec (exceptions)",
    unit="events",
)

webhook_events_dlq = meter.create_counter(
    "webhook.events.dlq",
    description="Nombre total d'événements webhook déplacés vers Dead Letter Queue",
    unit="events",
)

webhook_events_retried = meter.create_counter(
    "webhook.events.retried",
    description="Nombre total d'événements webhook reclaimed pour retry (XCLAIM)",
    unit="events",
)

webhook_processing_duration = meter.create_histogram(
    "webhook.processing.duration",
    description="Durée de traitement des événements webhook (secondes)",
    unit="s",
)


def _get_consumer_lag_sync(options) -> list:
    """
    Callback synchrone pour mesurer le consumer lag (messages pending).

    Note: OpenTelemetry nécessite des callbacks synchrones pour les métriques observables.
    Comme Redis async ne peut pas être utilisé dans un contexte synchrone,
    nous retournons une liste vide. Les métriques réelles sont mises à jour
    lors du traitement des messages.
    """
    # Les métriques de lag sont maintenant suivies via des compteurs
    # lors du traitement réel des messages
    return []


def _get_dlq_length_sync(options) -> list:
    """
    Callback synchrone pour mesurer la longueur de la DLQ.

    Note: OpenTelemetry nécessite des callbacks synchrones pour les métriques observables.
    Les métriques réelles sont mises à jour lors du déplacement vers la DLQ.
    """
    # Les métriques DLQ sont suivies via webhook_events_dlq counter
    return []


# Variables globales pour stocker les dernières valeurs des métriques
_last_consumer_lag = 0
_last_dlq_length = 0


async def _update_consumer_lag():
    """Met à jour la métrique de consumer lag de manière asynchrone."""
    global _last_consumer_lag
    if not webhook_redis_client:
        _last_consumer_lag = 0
        return 0
    try:
        pending = await webhook_redis_client.xpending(WEBHOOK_STREAM_NAME, WEBHOOK_CONSUMER_GROUP)
        _last_consumer_lag = pending.get("pending", 0) if pending else 0
        return _last_consumer_lag
    except Exception:
        _last_consumer_lag = 0
        return 0


async def _update_dlq_length():
    """Met à jour la métrique de longueur de la DLQ de manière asynchrone."""
    global _last_dlq_length
    if not webhook_redis_client:
        _last_dlq_length = 0
        return 0
    try:
        _last_dlq_length = await webhook_redis_client.xlen(f"{WEBHOOK_STREAM_NAME}:dlq")
        return _last_dlq_length
    except Exception:
        _last_dlq_length = 0
        return 0


def _get_consumer_lag_callback(options) -> list:
    """Callback synchrone qui retourne la dernière valeur de consumer lag."""
    from opentelemetry.metrics import Observation

    return [Observation(_last_consumer_lag)]


def _get_dlq_length_callback(options) -> list:
    """Callback synchrone qui retourne la dernière valeur de DLQ length."""
    from opentelemetry.metrics import Observation

    return [Observation(_last_dlq_length)]


# Gauges observables avec callbacks synchrones
webhook_consumer_lag_gauge = meter.create_observable_gauge(
    "webhook.consumer.lag",
    callbacks=[_get_consumer_lag_callback],
    description="Nombre de messages pending (non-ACK) dans Redis Streams",
    unit="messages",
)

webhook_dlq_length_gauge = meter.create_observable_gauge(
    "webhook.dlq.length",
    callbacks=[_get_dlq_length_callback],
    description="Nombre de messages dans la Dead Letter Queue",
    unit="messages",
)

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
    # Capturer le contexte de trace ACTUEL (du webhook endpoint)
    current_span = trace.get_current_span()
    span_context = current_span.get_span_context()

    # Extraire trace_id et span_id pour propagation
    trace_id = format(span_context.trace_id, "032x") if span_context.is_valid else None
    span_id = format(span_context.span_id, "016x") if span_context.is_valid else None

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
            # Sérialiser l'événement avec le contexte de trace
            event_data = {
                "event_type": event.event_type,
                "user_id": event.user_id,
                "realm_id": event.realm_id,
                "event_time": str(event.event_time),  # Utiliser event_time au lieu de timestamp
                "payload": event.model_dump_json(exclude_none=True),
                "added_at": datetime.now(UTC).isoformat(),
                "delivery_attempts": "0",  # Compteur de tentatives
                # Propagation du contexte de trace pour corrélation
                "trace_id": trace_id,
                "parent_span_id": span_id,
            }

            # XADD: Ajoute au stream avec ID auto-généré
            message_id = await webhook_redis_client.xadd(WEBHOOK_STREAM_NAME, event_data)

            # Métrique OpenTelemetry: événement produit
            webhook_events_produced.add(1, {"event_type": event.event_type})

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

                # 3. Mettre à jour les métriques observables
                await _update_consumer_lag()
                await _update_dlq_length()

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
    # Récupérer le contexte de trace propagé
    original_trace_id = message_data.get("trace_id")
    parent_span_id = message_data.get("parent_span_id")

    span_attributes = {
        "messaging.system": "redis-streams",
        "messaging.destination": WEBHOOK_STREAM_NAME,
        "messaging.message.id": message_id,
        "event.type": message_data.get("event_type"),
        # Lier au trace original du webhook
        "original.trace_id": original_trace_id,
        "original.parent_span_id": parent_span_id,
    }

    with tracer.start_as_current_span(
        "process_webhook_message", kind=trace.SpanKind.CONSUMER, attributes=span_attributes
    ) as span:
        # Log avec le trace_id original pour corrélation
        if original_trace_id:
            logger.info(
                f"Processing webhook from original trace_id={original_trace_id}, "
                f"message_id={message_id}, type={message_data.get('event_type')}"
            )
        # Métrique OpenTelemetry: événement consommé
        event_type = message_data.get("event_type", "unknown")
        webhook_events_consumed.add(1, {"event_type": event_type})

        # Mesure de la durée de traitement
        start_time = time.time()

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

                    # Métrique OpenTelemetry: événement ACK
                    webhook_events_acked.add(1, {"event_type": event.event_type})

                    # Métrique OpenTelemetry: durée de traitement
                    duration = time.time() - start_time
                    webhook_processing_duration.record(
                        duration, {"event_type": event.event_type, "success": "true"}
                    )

                    logger.info(
                        f"Webhook traité avec succès: id={message_id}, "
                        f"type={event.event_type}, message={result.message}"
                    )

                    span.add_event("Webhook traité avec succès")

                else:
                    # Échec mais pas d'exception: laisser pending pour retry
                    # Métrique OpenTelemetry: échec (sera retry)
                    webhook_events_failed.add(
                        1, {"event_type": event.event_type, "reason": "handler_failure"}
                    )

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
            # Métrique OpenTelemetry: exception
            webhook_events_failed.add(1, {"event_type": event_type, "reason": "exception"})

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

                # Métrique OpenTelemetry: retry (reclaim)
                if claimed:
                    webhook_events_retried.add(len(claimed))

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

        # Métrique OpenTelemetry: message vers DLQ
        event_type = message_data.get("event_type", "unknown")
        webhook_events_dlq.add(1, {"event_type": event_type})

        logger.error(
            f"Message déplacé vers DLQ: original_id={message_id}, "
            f"dlq_id={dlq_id}, type={message_data.get('event_type')}, "
            f"original_trace_id={message_data.get('trace_id')}"
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
