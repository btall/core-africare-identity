"""
Processeur webhook pour le background consumer Redis Streams.

Ce module sert de pont entre le consumer Redis Streams et les handlers
de synchronisation Keycloak existants. Il route les événements vers
le handler approprié selon le type d'événement.

Architecture:
    Redis Streams → webhook_processor → route_webhook_event → handler spécifique

Handlers supportés:
    - REGISTER: sync_user_registration (création patient/professional)
    - UPDATE_PROFILE: sync_profile_update (mise à jour profil)
    - UPDATE_EMAIL: sync_email_update (mise à jour email)
    - LOGIN: track_user_login (tracking analytics)
    - DELETE: sync_user_deletion (suppression/anonymisation patient/professional)
"""

import logging

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.keycloak import KeycloakWebhookEvent, SyncResult
from app.services.keycloak_sync_service import (
    sync_email_update,
    sync_profile_update,
    sync_user_deletion,
    sync_user_registration,
    track_user_login,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Mapping type d'événement → handler
EVENT_HANDLERS = {
    "REGISTER": sync_user_registration,
    "UPDATE_PROFILE": sync_profile_update,
    "UPDATE_EMAIL": sync_email_update,
    "LOGIN": track_user_login,
    "DELETE": sync_user_deletion,
}


async def route_webhook_event(db: AsyncSession, event: KeycloakWebhookEvent) -> SyncResult:
    """
    Route un événement webhook vers le handler approprié.

    Cette fonction est appelée par le background consumer Redis Streams
    pour chaque événement consommé depuis le stream.

    Args:
        db: Session de base de données async
        event: Événement Keycloak désérialisé depuis Redis Streams

    Returns:
        SyncResult avec success=True/False et message descriptif

    Raises:
        ValueError: Si type d'événement non supporté

    Example:
        >>> event = KeycloakWebhookEvent(event_type="REGISTER", ...)
        >>> async with async_session_maker() as db:
        ...     result = await route_webhook_event(db, event)
        ...     print(f"Success: {result.success}, Message: {result.message}")
    """
    with tracer.start_as_current_span("route_webhook_event") as span:
        span.set_attribute("event.type", event.event_type)
        span.set_attribute("event.user_id", event.user_id)

        # Récupérer le handler
        handler = EVENT_HANDLERS.get(event.event_type)

        if not handler:
            error_msg = f"Unsupported event type: {event.event_type}"
            logger.warning(f"Type d'événement non supporté: {event.event_type}")

            span.set_status(trace.Status(trace.StatusCode.ERROR, error_msg))

            # Retourner un échec au lieu de raise pour éviter retry infini
            return SyncResult(
                success=False,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=None,
                message=error_msg,
            )

        # Appeler le handler approprié
        logger.info(
            f"Routing événement vers handler: type={event.event_type}, "
            f"handler={handler.__name__}, user_id={event.user_id}"
        )

        try:
            result = await handler(db, event)

            span.set_attribute("sync.success", result.success)
            span.set_attribute("sync.message", result.message)

            logger.info(
                f"Handler exécuté: type={event.event_type}, "
                f"success={result.success}, message={result.message}"
            )

            return result

        except Exception as e:
            # Laisser l'exception remonter pour retry automatique
            logger.error(
                f"Erreur dans handler {handler.__name__} pour événement {event.event_type}: {e}",
                exc_info=True,
            )
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise
