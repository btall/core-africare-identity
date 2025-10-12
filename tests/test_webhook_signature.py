"""Tests unitaires pour la vérification de signature webhook."""

import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.webhook_security import compute_signature, verify_signature, verify_webhook_request


class TestComputeSignature:
    """Tests pour le calcul de signature HMAC-SHA256."""

    def test_compute_signature_valid(self):
        """Test calcul de signature valide."""
        payload = b'{"type":"REGISTER","userId":"test-123"}'
        secret = "test-secret"
        timestamp = "1234567890"

        signature = compute_signature(payload, secret, timestamp)

        # Vérifier format hexadécimal (64 caractères pour SHA256)
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)

    def test_compute_signature_deterministic(self):
        """Test que la même entrée produit la même signature."""
        payload = b'{"data":"test"}'
        secret = "secret"
        timestamp = "1000000"

        sig1 = compute_signature(payload, secret, timestamp)
        sig2 = compute_signature(payload, secret, timestamp)

        assert sig1 == sig2

    def test_compute_signature_different_payloads(self):
        """Test que des payloads différents produisent des signatures différentes."""
        secret = "secret"
        timestamp = "1000000"

        sig1 = compute_signature(b'{"data":"test1"}', secret, timestamp)
        sig2 = compute_signature(b'{"data":"test2"}', secret, timestamp)

        assert sig1 != sig2

    def test_compute_signature_different_secrets(self):
        """Test que des secrets différents produisent des signatures différentes."""
        payload = b'{"data":"test"}'
        timestamp = "1000000"

        sig1 = compute_signature(payload, "secret1", timestamp)
        sig2 = compute_signature(payload, "secret2", timestamp)

        assert sig1 != sig2

    def test_compute_signature_different_timestamps(self):
        """Test que des timestamps différents produisent des signatures différentes."""
        payload = b'{"data":"test"}'
        secret = "secret"

        sig1 = compute_signature(payload, secret, "1000000")
        sig2 = compute_signature(payload, secret, "2000000")

        assert sig1 != sig2


class TestVerifySignature:
    """Tests pour la vérification de signature."""

    def test_verify_signature_valid(self):
        """Test vérification d'une signature valide."""
        payload = b'{"type":"REGISTER"}'
        secret = "test-secret"
        timestamp = str(int(time.time()))

        signature = compute_signature(payload, secret, timestamp)

        with patch("app.core.config.settings.WEBHOOK_SECRET", secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                result = verify_signature(payload, signature, timestamp)

        assert result.verified is True
        assert result.reason is None

    def test_verify_signature_invalid_signature(self):
        """Test vérification avec signature invalide."""
        payload = b'{"type":"REGISTER"}'
        secret = "test-secret"
        timestamp = str(int(time.time()))

        with patch("app.core.config.settings.WEBHOOK_SECRET", secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                result = verify_signature(payload, "invalid_signature", timestamp)

        assert result.verified is False
        assert result.reason is not None

    def test_verify_signature_expired_timestamp(self):
        """Test vérification avec timestamp expiré."""
        payload = b'{"type":"REGISTER"}'
        secret = "test-secret"
        # Timestamp de plus de 5 minutes dans le passé
        old_timestamp = str(int(time.time()) - 400)

        signature = compute_signature(payload, secret, old_timestamp)

        with patch("app.core.config.settings.WEBHOOK_SECRET", secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                result = verify_signature(payload, signature, old_timestamp)

        assert result.verified is False
        assert "expiré" in result.reason

    def test_verify_signature_future_timestamp(self):
        """Test vérification avec timestamp futur (hors tolérance)."""
        payload = b'{"type":"REGISTER"}'
        secret = "test-secret"
        # Timestamp 2 minutes dans le futur (hors tolérance de 60s)
        future_timestamp = str(int(time.time()) + 120)

        signature = compute_signature(payload, secret, future_timestamp)

        with patch("app.core.config.settings.WEBHOOK_SECRET", secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                result = verify_signature(payload, signature, future_timestamp)

        assert result.verified is False
        assert "futur" in result.reason

    def test_verify_signature_timing_attack_protection(self):
        """Test que la comparaison utilise hmac.compare_digest (timing attack safe)."""
        payload = b'{"type":"REGISTER"}'
        secret = "test-secret"
        timestamp = str(int(time.time()))

        correct_signature = compute_signature(payload, secret, timestamp)
        # Signature presque correcte (un caractère différent)
        almost_correct = correct_signature[:-1] + ("a" if correct_signature[-1] != "a" else "b")

        with patch("app.core.config.settings.WEBHOOK_SECRET", secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                result = verify_signature(payload, almost_correct, timestamp)

        # Doit être invalide même avec un seul caractère différent
        assert result.verified is False
        assert "invalide" in result.reason


class TestVerifyWebhookRequest:
    """Tests pour la vérification de requête webhook FastAPI."""

    @pytest.mark.asyncio
    async def test_verify_webhook_request_valid(self):
        """Test vérification d'une requête webhook valide."""
        payload = b'{"type":"REGISTER","userId":"test-123"}'
        secret = "test-secret"
        timestamp = str(int(time.time()))
        signature = compute_signature(payload, secret, timestamp)

        # Mock Request avec méthode body async
        class MockRequest:
            def __init__(self):
                self.headers = {
                    "X-Keycloak-Signature": signature,
                    "X-Keycloak-Timestamp": timestamp,
                }

            async def body(self):
                return payload

        mock_request = MockRequest()

        with patch("app.core.config.settings.WEBHOOK_SECRET", secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                result = await verify_webhook_request(mock_request)

        # verify_webhook_request returns WebhookSignature, not WebhookVerificationResponse
        assert result.signature == signature
        assert result.timestamp == timestamp

    @pytest.mark.asyncio
    async def test_verify_webhook_request_missing_signature_header(self):
        """Test avec header X-Keycloak-Signature manquant."""
        payload = b'{"type":"REGISTER"}'

        class MockRequest:
            def __init__(self):
                self.headers = {"X-Keycloak-Timestamp": str(int(time.time()))}

            async def body(self):
                return payload

        mock_request = MockRequest()

        with pytest.raises(HTTPException) as exc_info:
            await verify_webhook_request(mock_request)

        assert exc_info.value.status_code == 400
        assert "Missing X-Keycloak-Signature header" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_webhook_request_missing_timestamp_header(self):
        """Test avec header X-Keycloak-Timestamp manquant."""
        payload = b'{"type":"REGISTER"}'
        signature = "fake_signature"

        class MockRequest:
            def __init__(self):
                self.headers = {"X-Keycloak-Signature": signature}

            async def body(self):
                return payload

        mock_request = MockRequest()

        with pytest.raises(HTTPException) as exc_info:
            await verify_webhook_request(mock_request)

        assert exc_info.value.status_code == 400
        assert "Missing X-Keycloak-Timestamp header" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_webhook_request_invalid_signature(self):
        """Test avec signature invalide."""
        payload = b'{"type":"REGISTER"}'
        secret = "test-secret"
        timestamp = str(int(time.time()))

        class MockRequest:
            def __init__(self):
                self.headers = {
                    "X-Keycloak-Signature": "invalid_signature_hex",
                    "X-Keycloak-Timestamp": timestamp,
                }

            async def body(self):
                return payload

        mock_request = MockRequest()

        with patch("app.core.config.settings.WEBHOOK_SECRET", secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                with pytest.raises(HTTPException) as exc_info:
                    await verify_webhook_request(mock_request)

        assert exc_info.value.status_code == 401
        assert "Invalid webhook signature" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_webhook_request_expired_timestamp(self):
        """Test avec timestamp expiré."""
        payload = b'{"type":"REGISTER"}'
        secret = "test-secret"
        old_timestamp = str(int(time.time()) - 400)  # 6 minutes dans le passé
        signature = compute_signature(payload, secret, old_timestamp)

        class MockRequest:
            def __init__(self):
                self.headers = {
                    "X-Keycloak-Signature": signature,
                    "X-Keycloak-Timestamp": old_timestamp,
                }

            async def body(self):
                return payload

        mock_request = MockRequest()

        with patch("app.core.config.settings.WEBHOOK_SECRET", secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                with pytest.raises(HTTPException) as exc_info:
                    await verify_webhook_request(mock_request)

        assert exc_info.value.status_code == 401
        assert "Invalid webhook signature" in exc_info.value.detail
