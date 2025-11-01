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

# Clients Keycloak autorisés pour la synchronisation patient/professional
# Les autres clients (ex: admin portal) sont ignorés
ALLOWED_CLIENT_IDS = {
    "apps-africare-patient-portal",
    "apps-africare-provider-portal",
}

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
        span.set_attribute("event.client_id", event.client_id or "null")

        # Vérifier si le client est autorisé pour la synchronisation
        # Les actions admin console (ADMIN_UPDATE) sont ignorées
        if event.event_type.startswith("ADMIN_"):
            logger.info(
                f"Événement admin console ignoré: type={event.event_type}, "
                f"user_id={event.user_id}, clientId={event.client_id or 'null'}"
            )
            span.add_event(
                "Événement admin console ignoré",
                {"event_type": event.event_type, "client_id": event.client_id or "null"},
            )

            return SyncResult(
                success=True,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=None,
                message=f"Événement admin console ignoré: {event.event_type}",
            )

        # Pour les événements normaux, filtrer par clientId autorisé
        # Exception: DELETE peut avoir clientId=null (suppression admin console)
        if (
            event.event_type != "DELETE"
            and event.client_id
            and event.client_id not in ALLOWED_CLIENT_IDS
        ):
            logger.info(
                f"Événement ignoré: clientId={event.client_id} non autorisé "
                f"(autorisés: {', '.join(ALLOWED_CLIENT_IDS)}). "
                f"Type={event.event_type}, user_id={event.user_id}"
            )
            span.add_event(
                "Événement ignoré: client non autorisé",
                {"client_id": event.client_id, "allowed_clients": ", ".join(ALLOWED_CLIENT_IDS)},
            )

            # Retourner un SUCCÈS (pas un échec) pour ACK le message
            # Les admins n'ont pas besoin d'être synchronisés comme patients/professionals
            return SyncResult(
                success=True,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=None,
                message=f"Événement ignoré: clientId {event.client_id} non autorisé (admin)",
            )

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
