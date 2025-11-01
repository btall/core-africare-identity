"""Module de sécurité pour la vérification des webhooks Keycloak.

Ce module implémente la vérification de signature HMAC-SHA256 pour
garantir l'authenticité et l'intégrité des événements webhook reçus.
"""

import hashlib
import hmac
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

from app.core.config import settings
from app.schemas.keycloak import WebhookSignature, WebhookVerificationResponse

logger = logging.getLogger(__name__)


def compute_signature(payload: bytes, secret: str, timestamp: str) -> str:
    """
    Calcule la signature HMAC-SHA256 d'un payload webhook.

    Args:
        payload: Corps de la requête webhook (bytes)
        secret: Secret partagé avec Keycloak
        timestamp: Timestamp de la requête

    Returns:
        Signature hexadécimale (64 caractères)
    """
    # Construire le message signé: timestamp.payload
    signed_payload = f"{timestamp}.".encode() + payload

    # Calculer HMAC-SHA256
    signature = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

    return signature


def verify_signature(
    payload: bytes,
    signature: str,
    timestamp: str,
    secret: str | None = None,
    tolerance: int | None = None,
) -> WebhookVerificationResponse:
    """
    Vérifie la signature d'un webhook Keycloak.

    Args:
        payload: Corps de la requête webhook (bytes)
        signature: Signature fournie dans les headers
        timestamp: Timestamp fourni dans les headers
        secret: Secret partagé (utilise settings.WEBHOOK_SECRET par défaut)
        tolerance: Tolérance timestamp en secondes (utilise settings par défaut)

    Returns:
        WebhookVerificationResponse avec verified=True si valide

    Raises:
        ValueError: Si signature ou timestamp invalide
    """
    secret = secret or settings.WEBHOOK_SECRET
    tolerance = tolerance or settings.WEBHOOK_SIGNATURE_TOLERANCE

    # 1. Vérifier que le timestamp est valide
    try:
        request_time = datetime.fromtimestamp(int(timestamp))
    except (ValueError, OverflowError) as e:
        logger.warning(f"Timestamp webhook invalide: {timestamp} - {e}")
        return WebhookVerificationResponse(
            verified=False, reason=f"Timestamp invalide: {timestamp}"
        )

    # 2. Vérifier que le timestamp est dans la fenêtre de tolérance
    now = datetime.now()
    max_age = timedelta(seconds=tolerance)

    if (now - request_time) > max_age:
        logger.warning(
            f"Webhook expiré: timestamp={timestamp}, age={(now - request_time).total_seconds()}s"
        )
        return WebhookVerificationResponse(verified=False, reason=f"Webhook expiré (>{tolerance}s)")

    if request_time > (now + timedelta(seconds=60)):
        logger.warning(f"Webhook avec timestamp dans le futur: {timestamp}")
        return WebhookVerificationResponse(verified=False, reason="Timestamp dans le futur")

    # 3. Calculer la signature attendue
    expected_signature = compute_signature(payload, secret, timestamp)

    # 4. Comparer les signatures (constant-time pour éviter timing attacks)
    signatures_match = hmac.compare_digest(signature.lower(), expected_signature.lower())

    if not signatures_match:
        logger.warning(
            f"Signature webhook invalide: reçue={signature[:10]}..., "
            f"attendue={expected_signature[:10]}..."
        )
        return WebhookVerificationResponse(verified=False, reason="Signature invalide")

    # Tout est OK
    logger.debug("Webhook signature vérifiée avec succès")
    return WebhookVerificationResponse(verified=True, reason=None)


async def verify_webhook_request(request: Request) -> WebhookSignature:
    """
    Extrait et vérifie la signature d'une requête webhook FastAPI.

    Args:
        request: Objet Request FastAPI

    Returns:
        WebhookSignature avec signature et timestamp

    Raises:
        HTTPException: Si headers manquants ou signature invalide
    """
    # 1. Extraire les headers de signature
    signature = request.headers.get("X-Keycloak-Signature")
    timestamp = request.headers.get("X-Keycloak-Timestamp")

    if not signature:
        logger.error("Header X-Keycloak-Signature manquant")
        raise HTTPException(status_code=400, detail="Missing X-Keycloak-Signature header")

    if not timestamp:
        logger.error("Header X-Keycloak-Timestamp manquant")
        raise HTTPException(status_code=400, detail="Missing X-Keycloak-Timestamp header")

    # 2. Lire le corps de la requête
    body = await request.body()

    # 3. Vérifier la signature
    verification = verify_signature(payload=body, signature=signature, timestamp=timestamp)

    if not verification.verified:
        logger.error(f"Webhook signature invalide: {verification.reason}")
        raise HTTPException(
            status_code=401, detail=f"Invalid webhook signature: {verification.reason}"
        )

    # Tout est valide
    return WebhookSignature(signature=signature, timestamp=timestamp)


def generate_test_signature(payload: str, secret: str | None = None) -> tuple[str, str]:
    """
    Génère une signature de test pour les tests unitaires.

    Args:
        payload: Corps du webhook (string JSON)
        secret: Secret à utiliser (défaut: settings.WEBHOOK_SECRET)

    Returns:
        Tuple (signature, timestamp)
    """
    secret = secret or settings.WEBHOOK_SECRET
    timestamp = str(int(datetime.now().timestamp()))

    signature = compute_signature(payload.encode("utf-8"), secret, timestamp)

    return signature, timestamp
