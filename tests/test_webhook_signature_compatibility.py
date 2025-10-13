"""Test de compatibilité de signature entre Keycloak (Java) et FastAPI (Python).

Ce test vérifie que la signature HMAC-SHA256 calculée côté Python
correspond exactement à celle calculée côté Java.

Algorithme de signature (identique Java/Python):
    HMAC-SHA256(secret, timestamp + "." + jsonPayload)
"""

import hashlib
import hmac
import json
from datetime import datetime
from typing import ClassVar

import pytest

from app.core.webhook_security import compute_signature, verify_signature


class TestWebhookSignatureCompatibility:
    """Tests de compatibilité Java/Python pour la signature des webhooks."""

    SECRET: ClassVar[str] = "test-webhook-secret-123"
    # Timestamp actuel pour éviter expiration (tolérance par défaut: 300s)
    TIMESTAMP: ClassVar[str] = str(int(datetime.now().timestamp()))

    PAYLOAD: ClassVar[dict] = {
        "eventType": "REGISTER",
        "eventTime": 1704067200000,
        "realmId": "africare-dev",
        "userId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "ipAddress": "192.168.1.1",
        "user": {
            "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "username": "amadou.diallo",
            "email": "amadou.diallo@example.sn",
            "emailVerified": True,
            "firstName": "Amadou",
            "lastName": "Diallo",
            "enabled": True,
            "createdTimestamp": 1704067200000,
        },
    }

    def test_compute_signature_format(self):
        """Vérifie que la signature générée est au bon format (hexadécimal 64 caractères)."""
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")
        signature = compute_signature(payload, self.SECRET, self.TIMESTAMP)

        # Vérifications format
        assert isinstance(signature, str)
        assert len(signature) == 64  # HMAC-SHA256 hex = 64 caractères
        assert all(c in "0123456789abcdef" for c in signature)  # Hexadécimal lowercase

    def test_compute_signature_includes_timestamp(self):
        """Vérifie que le timestamp est inclus dans le calcul de la signature."""
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")

        # Générer deux signatures avec des timestamps différents
        signature1 = compute_signature(payload, self.SECRET, "1704067200")
        signature2 = compute_signature(payload, self.SECRET, "1704067300")

        # Les signatures DOIVENT être différentes si le timestamp est inclus
        assert signature1 != signature2

    def test_compute_signature_deterministic(self):
        """Vérifie que la signature est déterministe (même input = même output)."""
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")

        signature1 = compute_signature(payload, self.SECRET, self.TIMESTAMP)
        signature2 = compute_signature(payload, self.SECRET, self.TIMESTAMP)

        # Même payload + timestamp + secret = même signature
        assert signature1 == signature2

    def test_compute_signature_java_compatibility(self):
        """Vérifie la compatibilité avec l'algorithme Java de Keycloak.

        Simule le calcul Java:
            String signedPayload = timestamp + "." + jsonPayload;
            HMAC-SHA256(secret, signedPayload)
        """
        # Utiliser un timestamp fixe pour ce test algorithmique
        fixed_timestamp = "1704067200"
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")

        # Calcul Python (via fonction)
        python_signature = compute_signature(payload, self.SECRET, fixed_timestamp)

        # Simule calcul Java (manuellement)
        signed_payload = f"{fixed_timestamp}.".encode() + payload
        java_signature = hmac.new(
            self.SECRET.encode("utf-8"), signed_payload, hashlib.sha256
        ).hexdigest()

        # Les deux signatures DOIVENT être identiques
        assert python_signature == java_signature

    def test_verify_signature_valid(self):
        """Vérifie qu'une signature valide est acceptée."""
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")
        signature = compute_signature(payload, self.SECRET, self.TIMESTAMP)

        # Vérification
        result = verify_signature(payload, signature, self.TIMESTAMP, self.SECRET)

        assert result.verified is True
        assert result.reason is None

    def test_verify_signature_invalid(self):
        """Vérifie qu'une signature invalide est rejetée."""
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")
        wrong_signature = "0" * 64  # Signature invalide

        # Vérification
        result = verify_signature(payload, wrong_signature, self.TIMESTAMP, self.SECRET)

        assert result.verified is False
        assert result.reason == "Signature invalide"

    def test_verify_signature_tampered_payload(self):
        """Vérifie qu'un payload modifié est détecté."""
        original_payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")
        signature = compute_signature(original_payload, self.SECRET, self.TIMESTAMP)

        # Modifier le payload APRÈS génération de signature
        tampered_payload = original_payload.replace(b"Amadou", b"HACKER")

        # Vérification avec payload modifié
        result = verify_signature(tampered_payload, signature, self.TIMESTAMP, self.SECRET)

        assert result.verified is False
        assert result.reason == "Signature invalide"

    def test_verify_signature_wrong_secret(self):
        """Vérifie qu'un secret incorrect est détecté."""
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")
        signature = compute_signature(payload, self.SECRET, self.TIMESTAMP)

        # Vérification avec un autre secret
        wrong_secret = "wrong-secret-456"
        result = verify_signature(payload, signature, self.TIMESTAMP, wrong_secret)

        assert result.verified is False
        assert result.reason == "Signature invalide"

    def test_verify_signature_timestamp_tolerance(self):
        """Vérifie la tolérance de timestamp (5 minutes par défaut)."""
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")

        # Timestamp actuel
        now_timestamp = str(int(datetime.now().timestamp()))
        signature = compute_signature(payload, self.SECRET, now_timestamp)

        # Vérification avec tolérance de 300 secondes (5 minutes)
        result = verify_signature(payload, signature, now_timestamp, self.SECRET, tolerance=300)

        assert result.verified is True

    def test_verify_signature_expired_timestamp(self):
        """Vérifie qu'un timestamp expiré est rejeté."""
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")

        # Timestamp très ancien (2020-01-01)
        old_timestamp = "1577836800"
        signature = compute_signature(payload, self.SECRET, old_timestamp)

        # Vérification avec tolérance stricte de 60 secondes
        result = verify_signature(payload, signature, old_timestamp, self.SECRET, tolerance=60)

        assert result.verified is False
        assert "expiré" in result.reason

    def test_signature_case_insensitive(self):
        """Vérifie que la comparaison de signature est insensible à la casse."""
        payload = json.dumps(self.PAYLOAD, separators=(",", ":")).encode("utf-8")
        signature_lower = compute_signature(payload, self.SECRET, self.TIMESTAMP)
        signature_upper = signature_lower.upper()

        # Vérification avec signature en majuscules
        result = verify_signature(payload, signature_upper, self.TIMESTAMP, self.SECRET)

        assert result.verified is True

    def test_real_world_scenario(self):
        """Test de scénario réel : webhook Keycloak complet."""
        # Payload réaliste d'un événement REGISTER
        keycloak_event = {
            "eventType": "REGISTER",
            "eventTime": 1704067200000,
            "realmId": "africare-dev",
            "userId": "user-123",
            "ipAddress": "41.82.45.123",
            "user": {
                "id": "user-123",
                "username": "fatou.sow",
                "email": "fatou.sow@example.sn",
                "emailVerified": False,
                "firstName": "Fatou",
                "lastName": "Sow",
                "enabled": True,
                "createdTimestamp": 1704067200000,
                "attributes": {
                    "country": ["Sénégal"],
                    "phone": ["+221771234567"],
                    "preferred_language": ["fr"],
                },
            },
        }

        payload_bytes = json.dumps(keycloak_event, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(datetime.now().timestamp()))
        secret = "africare-production-secret-2024"

        # Générer signature (comme Keycloak le ferait)
        signature = compute_signature(payload_bytes, secret, timestamp)

        # Vérifier signature (comme FastAPI le ferait)
        result = verify_signature(payload_bytes, signature, timestamp, secret, tolerance=300)

        assert result.verified is True
        assert result.reason is None


@pytest.mark.integration
class TestWebhookSignatureIntegration:
    """Tests d'intégration avec génération de test signatures."""

    def test_generate_test_signature_utility(self):
        """Vérifie la fonction utilitaire generate_test_signature."""
        from app.core.webhook_security import generate_test_signature

        payload_str = '{"userId":"123","action":"created"}'
        secret = "test-secret"

        signature, timestamp = generate_test_signature(payload_str, secret)

        # Vérifications
        assert isinstance(signature, str)
        assert len(signature) == 64
        assert isinstance(timestamp, str)
        assert timestamp.isdigit()

        # Vérifier que la signature est valide
        result = verify_signature(payload_str.encode("utf-8"), signature, timestamp, secret)
        assert result.verified is True
