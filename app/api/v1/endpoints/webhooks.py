"""Endpoint webhook pour la synchronisation Keycloak.

Ce module expose l'endpoint webhook qui reçoit les événements
de Keycloak et déclenche la synchronisation vers PostgreSQL.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.webhook_security import verify_webhook_request
from app.schemas.keycloak import (
    KeycloakWebhookEvent,
    SyncResult,
    WebhookHealthCheck,
)
from app.services.keycloak_sync_service import (
    sync_email_update,
    sync_profile_update,
    sync_user_registration,
    track_user_login,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

router = APIRouter()

# Stats pour health check (en mémoire, réinitialisées au redémarrage)
webhook_stats = {
    "last_event_received": None,
    "total_events_processed": 0,
    "failed_events_count": 0,
}


@router.post(
    "/keycloak",
    response_model=SyncResult,
    status_code=status.HTTP_200_OK,
    summary="Webhook Keycloak",
    description="Reçoit et traite les événements webhook de Keycloak pour synchronisation temps-réel",
    responses={
        200: {"description": "Événement traité avec succès"},
        400: {"description": "Événement invalide ou headers manquants"},
        401: {"description": "Signature webhook invalide"},
        500: {"description": "Erreur lors du traitement de l'événement"},
    },
)
async def receive_keycloak_webhook(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> SyncResult:
    """
    Endpoint webhook pour recevoir les événements Keycloak.

    Processus:
    1. Vérifier la signature HMAC-SHA256
    2. Parser l'événement
    3. Router vers le handler approprié selon le type
    4. Retourner le résultat de synchronisation

    Args:
        request: Requête FastAPI (contient le payload webhook)
        db: Session de base de données

    Returns:
        SyncResult avec les détails de la synchronisation

    Raises:
        HTTPException: Si signature invalide ou erreur de traitement
    """
    with tracer.start_as_current_span("receive_keycloak_webhook") as span:
        try:
            # 1. Vérifier la signature webhook
            await verify_webhook_request(request)
            logger.debug("Signature webhook vérifiée")

            # 2. Parser le corps de la requête
            body = await request.json()
            logger.info(f"Body: {body}")
            event = KeycloakWebhookEvent(**body)

            span.set_attribute("event.type", event.event_type)
            span.set_attribute("event.user_id", event.user_id)
            span.set_attribute("event.realm_id", event.realm_id)

            logger.info(
                f"Événement webhook reçu: type={event.event_type}, "
                f"user_id={event.user_id}, realm={event.realm_id}"
            )

            # 3. Router vers le handler approprié
            result = await _route_event(db, event)

            # 4. Mettre à jour les stats
            webhook_stats["last_event_received"] = datetime.now()
            webhook_stats["total_events_processed"] += 1

            if not result.success:
                webhook_stats["failed_events_count"] += 1

            span.set_attribute("sync.success", result.success)
            span.set_attribute("sync.message", result.message)

            logger.info(
                f"Événement traité: type={event.event_type}, success={result.success}, "
                f"message={result.message}"
            )

            return result

        except HTTPException:
            # Re-raise les exceptions HTTP (signature invalide, etc.)
            webhook_stats["failed_events_count"] += 1
            raise

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            webhook_stats["failed_events_count"] += 1

            logger.error(f"Erreur lors du traitement du webhook: {e}", exc_info=True)

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to process webhook: {e!s}",
            ) from e


@router.get(
    "/keycloak/health",
    response_model=WebhookHealthCheck,
    summary="Health check du webhook",
    description="Vérifie l'état de santé du webhook endpoint et retourne des statistiques",
)
async def webhook_health_check() -> WebhookHealthCheck:
    """
    Health check du webhook endpoint.

    Retourne l'état de santé et des statistiques d'utilisation.

    Returns:
        WebhookHealthCheck avec status et métriques
    """
    # Déterminer le status de santé
    total = webhook_stats["total_events_processed"]
    failed = webhook_stats["failed_events_count"]

    if total == 0:
        health_status = "healthy"  # Aucun événement encore
    elif failed / total < 0.1:  # Moins de 10% d'échecs
        health_status = "healthy"
    elif failed / total < 0.5:  # Entre 10% et 50% d'échecs
        health_status = "degraded"
    else:  # Plus de 50% d'échecs
        health_status = "unhealthy"

    return WebhookHealthCheck(
        status=health_status,
        webhook_endpoint="/api/v1/webhooks/keycloak",
        last_event_received=webhook_stats["last_event_received"],
        total_events_processed=webhook_stats["total_events_processed"],
        failed_events_count=webhook_stats["failed_events_count"],
    )


async def _route_event(db: AsyncSession, event: KeycloakWebhookEvent) -> SyncResult:
    """
    Route un événement webhook vers le handler approprié.

    Args:
        db: Session de base de données
        event: Événement Keycloak à traiter

    Returns:
        SyncResult du traitement

    Raises:
        ValueError: Si type d'événement non supporté
    """
    handlers = {
        "REGISTER": sync_user_registration,
        "UPDATE_PROFILE": sync_profile_update,
        "UPDATE_EMAIL": sync_email_update,
        "LOGIN": track_user_login,
    }

    handler = handlers.get(event.event_type)

    if not handler:
        logger.warning(f"Type d'événement non supporté: {event.event_type}")
        raise ValueError(f"Unsupported event type: {event.event_type}")

    # Appeler le handler
    return await handler(db, event)
