"""Endpoint webhook pour la synchronisation Keycloak.

Ce module expose l'endpoint webhook qui reçoit les événements
de Keycloak et les persiste dans Redis Streams pour traitement asynchrone.

Architecture résiliente:
    Keycloak → Webhook → XADD Redis Stream → Return 200 OK
                              ↓
                    Background Worker (traitement async)

Avantages:
    - Persistence: Événements survivent aux crashes
    - Retry automatique: Messages non-ACK sont reconsommés
    - Performance: Keycloak reçoit 200 OK immédiatement
    - Monitoring: XPENDING pour voir messages en cours
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi_errors_rfc9457 import create_responses
from opentelemetry import trace
from pydantic import BaseModel

from app.core.webhook_security import verify_webhook_request
from app.core.webhook_streams import add_webhook_event
from app.schemas.keycloak import (
    KeycloakWebhookEvent,
    WebhookHealthCheck,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

router = APIRouter()

# Stats pour health check (en mémoire, réinitialisées au redémarrage)
webhook_stats = {
    "last_event_received": None,
    "total_events_received": 0,
    "total_events_persisted": 0,
    "failed_to_persist_count": 0,
}


class WebhookAcceptedResponse(BaseModel):
    """Réponse immédiate du webhook (événement accepté et persisté)."""

    accepted: bool
    message_id: str
    event_type: str
    user_id: str
    timestamp: str
    message: str


@router.post(
    "/keycloak",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Webhook Keycloak (Resilient avec Redis Streams)",
    description="Reçoit, valide et persiste les événements Keycloak pour traitement asynchrone",
    responses={
        202: {"description": "Événement accepté et persisté dans Redis Streams"},
        **create_responses(),
    },
)
async def receive_keycloak_webhook(
    request: Request,
    event: Annotated[KeycloakWebhookEvent, Body()],
) -> WebhookAcceptedResponse:
    """
    Endpoint webhook résilient pour les événements Keycloak.

    Architecture:
        1. Vérification signature HMAC-SHA256
        2. Validation Pydantic de l'événement
        3. Persistence dans Redis Streams (XADD)
        4. Retour 202 Accepted immédiat
        5. Background worker traite l'événement de façon async

    Avantages vs traitement synchrone:
        - Keycloak reçoit 200 OK rapidement (pas de timeout)
        - Événements persistés (survivent aux crashes)
        - Retry automatique en cas d'échec
        - Scaling horizontal possible (consumer groups)

    Args:
        request: Requête FastAPI (pour vérification signature)
        event: Événement Keycloak validé par Pydantic

    Returns:
        WebhookAcceptedResponse avec message_id Redis et détails

    Raises:
        HTTPException: Si signature invalide ou échec persistence
    """
    with tracer.start_as_current_span("receive_keycloak_webhook") as span:
        try:
            # 1. Vérifier la signature webhook
            await verify_webhook_request(request)
            logger.debug("Signature webhook vérifiée")

            span.set_attribute("event.type", event.event_type)
            span.set_attribute("event.user_id", event.user_id)
            span.set_attribute("event.realm_id", event.realm_id)

            logger.info(
                f"Webhook reçu: type={event.event_type}, "
                f"user_id={event.user_id}, realm={event.realm_id}"
            )

            # 2. Persister dans Redis Streams (XADD)
            message_id = await add_webhook_event(event)

            # 3. Mettre à jour les stats
            webhook_stats["last_event_received"] = datetime.now()
            webhook_stats["total_events_received"] += 1
            webhook_stats["total_events_persisted"] += 1

            span.set_attribute("messaging.message.id", message_id)
            span.add_event("Événement persisté dans Redis Streams")

            logger.info(
                f"Webhook persisté: type={event.event_type}, "
                f"user_id={event.user_id}, message_id={message_id}"
            )

            return WebhookAcceptedResponse(
                accepted=True,
                message_id=message_id,
                event_type=event.event_type,
                user_id=event.user_id,
                timestamp=event.timestamp,
                message="Event accepted and queued for processing",
            )

        except HTTPException:
            # Re-raise les exceptions HTTP (signature invalide, etc.)
            webhook_stats["failed_to_persist_count"] += 1
            raise

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            webhook_stats["failed_to_persist_count"] += 1

            logger.error(f"Erreur lors de la persistence webhook: {e}", exc_info=True)

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist webhook event: {e!s}",
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
    Note: Les stats reflètent uniquement la persistence (XADD),
    pas le traitement asynchrone. Voir Redis XPENDING pour stats de traitement.

    Returns:
        WebhookHealthCheck avec status et métriques
    """
    # Déterminer le status de santé
    total = webhook_stats["total_events_received"]
    failed = webhook_stats["failed_to_persist_count"]

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
        total_events_processed=webhook_stats["total_events_persisted"],
        failed_events_count=webhook_stats["failed_to_persist_count"],
    )
