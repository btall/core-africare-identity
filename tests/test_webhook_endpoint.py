"""Tests unitaires pour l'endpoint webhook Keycloak."""

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.webhooks import router, webhook_stats
from app.core.webhook_security import compute_signature


@pytest.fixture
def app():
    """Fixture pour une application FastAPI minimale pour tests."""
    from app.core.database import get_session

    test_app = FastAPI()

    # Mock la dépendance de base de données
    async def mock_get_session():
        session = AsyncMock()
        yield session

    test_app.dependency_overrides[get_session] = mock_get_session
    test_app.include_router(router, prefix="/api/v1/webhooks")
    return test_app


@pytest.fixture
def client(app):
    """Fixture pour le client de test FastAPI."""
    return TestClient(app)


@pytest.fixture
def valid_webhook_payload():
    """Fixture pour un payload webhook valide."""
    import time

    current_time_ms = int(time.time() * 1000)

    return {
        "eventType": "REGISTER",
        "realmId": "africare",
        "clientId": "core-africare-identity",
        "userId": "test-user-123",
        "ipAddress": "192.168.1.1",
        "sessionId": "session-uuid",
        "user": {
            "username": "amadou.diallo",
            "email": "amadou.diallo@example.sn",
            "firstName": "Amadou",
            "lastName": "Diallo",
            "dateOfBirth": "1990-05-15",
            "gender": "male",
            "phone": "+221771234567",
            "country": "Sénégal",
            "preferredLanguage": "fr",
            "emailVerified": True,
            "enabled": True,
        },
        "eventTime": current_time_ms,
    }


@pytest.fixture
def webhook_secret():
    """Fixture pour le secret webhook."""
    return "test-webhook-secret-123"


def create_valid_headers(payload_json: str, secret: str) -> dict:
    """Créer des headers valides pour un webhook."""
    timestamp = str(int(time.time()))
    payload_bytes = payload_json.encode("utf-8")
    signature = compute_signature(payload_bytes, secret, timestamp)

    return {
        "Content-Type": "application/json",
        "X-Keycloak-Signature": signature,
        "X-Keycloak-Timestamp": timestamp,
    }


class TestReceiveKeycloakWebhook:
    """Tests pour l'endpoint POST /api/v1/webhooks/keycloak."""

    def test_receive_webhook_valid_register(self, client, valid_webhook_payload, webhook_secret):
        """Test réception d'un webhook REGISTER valide."""
        import json

        payload_json = json.dumps(valid_webhook_payload)
        headers = create_valid_headers(payload_json, webhook_secret)

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                with patch(
                    "app.api.v1.endpoints.webhooks.add_webhook_event",
                    new_callable=AsyncMock,
                ) as mock_add:
                    mock_add.return_value = "test-message-id-123"

                    response = client.post(
                        "/api/v1/webhooks/keycloak",
                        content=payload_json,
                        headers=headers,
                    )

        assert response.status_code == 202
        data = response.json()
        assert data["accepted"] is True
        assert data["event_type"] == "REGISTER"
        assert data["user_id"] == "test-user-123"
        assert data["message_id"] == "test-message-id-123"

    def test_receive_webhook_missing_signature_header(
        self, client, valid_webhook_payload, webhook_secret
    ):
        """Test webhook sans header X-Keycloak-Signature."""
        import json

        payload_json = json.dumps(valid_webhook_payload)
        headers = {
            "Content-Type": "application/json",
            "X-Keycloak-Timestamp": str(int(time.time())),
        }

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            response = client.post(
                "/api/v1/webhooks/keycloak",
                content=payload_json,
                headers=headers,
            )

        assert response.status_code == 400
        assert "Missing X-Keycloak-Signature header" in response.json()["detail"]

    def test_receive_webhook_missing_timestamp_header(
        self, client, valid_webhook_payload, webhook_secret
    ):
        """Test webhook sans header X-Keycloak-Timestamp."""
        import json

        payload_json = json.dumps(valid_webhook_payload)
        headers = {
            "Content-Type": "application/json",
            "X-Keycloak-Signature": "fake_signature",
        }

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            response = client.post(
                "/api/v1/webhooks/keycloak",
                content=payload_json,
                headers=headers,
            )

        assert response.status_code == 400
        assert "Missing X-Keycloak-Timestamp header" in response.json()["detail"]

    def test_receive_webhook_invalid_signature(self, client, valid_webhook_payload, webhook_secret):
        """Test webhook avec signature invalide."""
        import json

        payload_json = json.dumps(valid_webhook_payload)
        headers = {
            "Content-Type": "application/json",
            "X-Keycloak-Signature": "invalid_signature_hex",
            "X-Keycloak-Timestamp": str(int(time.time())),
        }

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                response = client.post(
                    "/api/v1/webhooks/keycloak",
                    content=payload_json,
                    headers=headers,
                )

        assert response.status_code == 401
        assert "Invalid webhook signature" in response.json()["detail"]

    def test_receive_webhook_expired_timestamp(self, client, valid_webhook_payload, webhook_secret):
        """Test webhook avec timestamp expiré."""
        import json

        payload_json = json.dumps(valid_webhook_payload)
        old_timestamp = str(int(time.time()) - 400)  # 6 minutes dans le passé
        payload_bytes = payload_json.encode("utf-8")
        signature = compute_signature(payload_bytes, webhook_secret, old_timestamp)

        headers = {
            "Content-Type": "application/json",
            "X-Keycloak-Signature": signature,
            "X-Keycloak-Timestamp": old_timestamp,
        }

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                response = client.post(
                    "/api/v1/webhooks/keycloak",
                    content=payload_json,
                    headers=headers,
                )

        assert response.status_code == 401
        assert "Invalid webhook signature" in response.json()["detail"]

    def test_receive_webhook_invalid_event_type(self, client, webhook_secret):
        """Test webhook avec type d'événement non supporté."""
        import json
        import time

        current_time_ms = int(time.time() * 1000)
        payload = {
            "eventType": "UNSUPPORTED_EVENT",
            "realmId": "africare",
            "userId": "test-user-123",
            "eventTime": current_time_ms,
            "user": {},
        }
        payload_json = json.dumps(payload)
        headers = create_valid_headers(payload_json, webhook_secret)

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                response = client.post(
                    "/api/v1/webhooks/keycloak",
                    content=payload_json,
                    headers=headers,
                )

        # Pydantic validation error
        assert response.status_code == 422

    def test_receive_webhook_update_profile(self, client, webhook_secret):
        """Test webhook UPDATE_PROFILE."""
        import json
        import time

        current_time_ms = int(time.time() * 1000)
        payload = {
            "eventType": "UPDATE_PROFILE",
            "realmId": "africare",
            "userId": "test-user-123",
            "eventTime": current_time_ms,
            "user": {
                "firstName": "Amadou Updated",
                "lastName": "Diallo Updated",
                "email": "amadou@example.sn",
                "emailVerified": True,
                "enabled": True,
            },
        }
        payload_json = json.dumps(payload)
        headers = create_valid_headers(payload_json, webhook_secret)

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                with patch(
                    "app.api.v1.endpoints.webhooks.add_webhook_event",
                    new_callable=AsyncMock,
                ) as mock_add:
                    mock_add.return_value = "test-message-id-123"

                    response = client.post(
                        "/api/v1/webhooks/keycloak",
                        content=payload_json,
                        headers=headers,
                    )

        assert response.status_code == 202
        data = response.json()
        assert data["accepted"] is True
        assert data["event_type"] == "UPDATE_PROFILE"
        assert data["user_id"] == "test-user-123"

    def test_receive_webhook_update_email(self, client, webhook_secret):
        """Test webhook UPDATE_EMAIL."""
        import json
        import time

        current_time_ms = int(time.time() * 1000)
        payload = {
            "eventType": "UPDATE_EMAIL",
            "realmId": "africare",
            "userId": "test-user-123",
            "eventTime": current_time_ms,
            "user": {
                "email": "new.email@example.sn",
                "emailVerified": True,
                "enabled": True,
            },
        }
        payload_json = json.dumps(payload)
        headers = create_valid_headers(payload_json, webhook_secret)

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                with patch(
                    "app.api.v1.endpoints.webhooks.add_webhook_event",
                    new_callable=AsyncMock,
                ) as mock_add:
                    mock_add.return_value = "test-message-id-123"

                    response = client.post(
                        "/api/v1/webhooks/keycloak",
                        content=payload_json,
                        headers=headers,
                    )

        assert response.status_code == 202
        data = response.json()
        assert data["accepted"] is True
        assert data["event_type"] == "UPDATE_EMAIL"
        assert data["user_id"] == "test-user-123"

    def test_receive_webhook_login(self, client, webhook_secret):
        """Test webhook LOGIN."""
        import json
        import time

        current_time_ms = int(time.time() * 1000)
        payload = {
            "eventType": "LOGIN",
            "realmId": "africare",
            "userId": "test-user-123",
            "ipAddress": "192.168.1.1",
            "sessionId": "session-uuid",
            "eventTime": current_time_ms,
            "user": None,
        }
        payload_json = json.dumps(payload)
        headers = create_valid_headers(payload_json, webhook_secret)

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                with patch(
                    "app.api.v1.endpoints.webhooks.add_webhook_event",
                    new_callable=AsyncMock,
                ) as mock_add:
                    mock_add.return_value = "test-message-id-123"

                    response = client.post(
                        "/api/v1/webhooks/keycloak",
                        content=payload_json,
                        headers=headers,
                    )

        assert response.status_code == 202
        data = response.json()
        assert data["accepted"] is True
        assert data["event_type"] == "LOGIN"
        assert data["user_id"] == "test-user-123"


class TestWebhookHealthCheck:
    """Tests pour l'endpoint GET /api/v1/webhooks/keycloak/health."""

    def test_health_check_no_events(self, client):
        """Test health check sans événements traités."""
        # Réinitialiser les stats avec les bons noms de clés
        webhook_stats["last_event_received"] = None
        webhook_stats["total_events_received"] = 0
        webhook_stats["total_events_persisted"] = 0
        webhook_stats["failed_to_persist_count"] = 0

        response = client.get("/api/v1/webhooks/keycloak/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["total_events_processed"] == 0
        assert data["failed_events_count"] == 0

    def test_health_check_healthy_status(self, client):
        """Test health check avec statut healthy (< 10% échecs)."""
        # Réinitialiser toutes les stats pour isolation
        webhook_stats["last_event_received"] = None
        webhook_stats["total_events_received"] = 100
        webhook_stats["total_events_persisted"] = 100
        webhook_stats["failed_to_persist_count"] = 5  # 5%

        response = client.get("/api/v1/webhooks/keycloak/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["total_events_processed"] == 100
        assert data["failed_events_count"] == 5

    def test_health_check_degraded_status(self, client):
        """Test health check avec statut degraded (10-50% échecs)."""
        # Réinitialiser toutes les stats pour isolation
        webhook_stats["last_event_received"] = None
        webhook_stats["total_events_received"] = 100
        webhook_stats["total_events_persisted"] = 100
        webhook_stats["failed_to_persist_count"] = 30  # 30%

        response = client.get("/api/v1/webhooks/keycloak/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    def test_health_check_unhealthy_status(self, client):
        """Test health check avec statut unhealthy (> 50% échecs)."""
        # Réinitialiser toutes les stats pour isolation
        webhook_stats["last_event_received"] = None
        webhook_stats["total_events_received"] = 100
        webhook_stats["total_events_persisted"] = 100
        webhook_stats["failed_to_persist_count"] = 60  # 60%

        response = client.get("/api/v1/webhooks/keycloak/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"

    def test_health_check_includes_endpoint_info(self, client):
        """Test que health check inclut les informations d'endpoint."""
        response = client.get("/api/v1/webhooks/keycloak/health")

        assert response.status_code == 200
        data = response.json()
        assert data["webhook_endpoint"] == "/api/v1/webhooks/keycloak"
