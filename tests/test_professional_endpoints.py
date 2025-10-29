"""Tests unitaires pour les endpoints professionnels avec authentification admin/webhook."""

import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.professionals import router
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
    test_app.include_router(router, prefix="/api/v1/professionals")
    return test_app


@pytest.fixture
def client(app):
    """Fixture pour le client de test FastAPI."""
    return TestClient(app)


@pytest.fixture
def webhook_secret():
    """Fixture pour le secret webhook."""
    return "test-webhook-secret-123"


@pytest.fixture
def admin_token():
    """Fixture pour un JWT admin valide (mock)."""
    return "mock-admin-jwt-token"


@pytest.fixture
def professional_payload():
    """Fixture pour un payload de création de professionnel."""
    return {
        "keycloak_user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "professional_id": "CNOM12345",
        "first_name": "Dr. Fatou",
        "last_name": "Sall",
        "title": "Dr",
        "specialty": "Cardiologie",
        "professional_type": "physician",
        "email": "fatou.sall@hospital.sn",
        "phone": "+221771234567",
        "facility_name": "Hôpital Principal de Dakar",
    }


def create_webhook_headers(payload_json: str, secret: str) -> dict:
    """Créer des headers valides pour un webhook."""
    timestamp = str(int(time.time()))
    payload_bytes = payload_json.encode("utf-8")
    signature = compute_signature(payload_bytes, secret, timestamp)

    return {
        "Content-Type": "application/json",
        "X-Keycloak-Signature": signature,
        "X-Keycloak-Timestamp": timestamp,
    }


class TestCreateProfessionalViaWebhook:
    """Tests pour la création de professionnel via webhook Keycloak."""

    def test_create_professional_webhook_valid_signature(
        self, client, professional_payload, webhook_secret
    ):
        """Test création via webhook avec signature valide → is_active=False."""
        from datetime import UTC, datetime

        payload_json = json.dumps(professional_payload)
        headers = create_webhook_headers(payload_json, webhook_secret)

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                with patch(
                    "app.services.professional_service.create_professional",
                    new_callable=AsyncMock,
                ) as mock_create:
                    # Créer un objet Professional mock avec attributs réels
                    from app.models.professional import Professional

                    mock_professional = Professional(
                        id=1,
                        keycloak_user_id=professional_payload["keycloak_user_id"],
                        first_name=professional_payload["first_name"],
                        last_name=professional_payload["last_name"],
                        is_active=False,  # Webhook crée avec is_active=False
                        is_verified=False,
                        email=professional_payload["email"],
                        phone=professional_payload["phone"],
                        specialty=professional_payload["specialty"],
                        professional_type=professional_payload["professional_type"],
                        title=professional_payload["title"],
                        is_available=True,
                        languages_spoken="fr",
                        digital_signature=None,
                        professional_id=professional_payload["professional_id"],
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                        created_by=None,
                        updated_by=None,
                    )

                    mock_create.return_value = mock_professional

                    response = client.post(
                        "/api/v1/professionals/",
                        content=payload_json,
                        headers=headers,
                    )

        assert response.status_code == 201
        data = response.json()
        assert data["is_active"] is False
        assert data["keycloak_user_id"] == professional_payload["keycloak_user_id"]

        # Vérifier que le service a été appelé avec current_user_id=None (webhook)
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args.kwargs["current_user_id"] is None

    def test_create_professional_webhook_invalid_signature(
        self, client, professional_payload, webhook_secret
    ):
        """Test création via webhook avec signature invalide → 401."""
        payload_json = json.dumps(professional_payload)
        headers = {
            "Content-Type": "application/json",
            "X-Keycloak-Signature": "invalid_signature_hex",
            "X-Keycloak-Timestamp": str(int(time.time())),
        }

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                response = client.post(
                    "/api/v1/professionals/",
                    content=payload_json,
                    headers=headers,
                )

        assert response.status_code == 401
        assert "Signature webhook invalide" in response.json()["detail"]

    def test_create_professional_webhook_missing_signature(self, client, professional_payload):
        """Test création via webhook sans signature → 401."""
        payload_json = json.dumps(professional_payload)
        headers = {
            "Content-Type": "application/json",
            "X-Keycloak-Timestamp": str(int(time.time())),
        }

        response = client.post(
            "/api/v1/professionals/",
            content=payload_json,
            headers=headers,
        )

        assert response.status_code == 401
        assert "Authentification requise" in response.json()["detail"]

    def test_create_professional_webhook_expired_timestamp(
        self, client, professional_payload, webhook_secret
    ):
        """Test création via webhook avec timestamp expiré → 401."""
        payload_json = json.dumps(professional_payload)
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
                    "/api/v1/professionals/",
                    content=payload_json,
                    headers=headers,
                )

        assert response.status_code == 401
        assert "Invalid webhook signature" in response.json()["detail"]


class TestCreateProfessionalViaAdmin:
    """Tests pour la création de professionnel via admin JWT."""

    def test_create_professional_admin_valid_token(self, client, professional_payload, admin_token):
        """Test création via admin avec JWT valide → is_active peut être True."""
        from datetime import UTC, datetime

        payload_json = json.dumps(professional_payload)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {admin_token}",
        }

        # Mock verify_token pour retourner un token admin valide
        mock_token_data = {
            "sub": "admin-user-id-123",
            "preferred_username": "admin",
            "realm_access": {"roles": ["admin"]},
        }

        with patch("app.core.security.verify_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_token_data

            with patch(
                "app.services.professional_service.create_professional",
                new_callable=AsyncMock,
            ) as mock_create:
                # Créer un objet Professional avec attributs réels
                from app.models.professional import Professional

                mock_professional = Professional(
                    id=2,
                    keycloak_user_id=professional_payload["keycloak_user_id"],
                    first_name=professional_payload["first_name"],
                    last_name=professional_payload["last_name"],
                    is_active=True,  # Admin peut créer avec is_active=True
                    is_verified=False,
                    email=professional_payload["email"],
                    phone=professional_payload["phone"],
                    specialty=professional_payload["specialty"],
                    professional_type=professional_payload["professional_type"],
                    title=professional_payload["title"],
                    is_available=True,
                    languages_spoken="fr",
                    digital_signature=None,
                    professional_id=professional_payload["professional_id"],
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    created_by="admin-user-id-123",
                    updated_by="admin-user-id-123",
                )

                mock_create.return_value = mock_professional

                response = client.post(
                    "/api/v1/professionals/",
                    content=payload_json,
                    headers=headers,
                )

        assert response.status_code == 201
        data = response.json()
        assert data["keycloak_user_id"] == professional_payload["keycloak_user_id"]
        assert data["created_by"] == "admin-user-id-123"

        # Vérifier que le service a été appelé avec current_user_id de l'admin
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args.kwargs["current_user_id"] == "admin-user-id-123"

    def test_create_professional_non_admin_token(self, client, professional_payload):
        """Test création par utilisateur non-admin → 403."""
        payload_json = json.dumps(professional_payload)
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer non-admin-token",
        }

        # Mock verify_token pour retourner un token sans rôle admin
        mock_token_data = {
            "sub": "regular-user-id-456",
            "preferred_username": "user",
            "realm_access": {"roles": ["patient"]},  # Pas de rôle admin
        }

        with patch("app.core.security.verify_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_token_data

            response = client.post(
                "/api/v1/professionals/",
                content=payload_json,
                headers=headers,
            )

        assert response.status_code == 403
        assert "administrateurs" in response.json()["detail"]

    def test_create_professional_invalid_token(self, client, professional_payload):
        """Test création avec JWT invalide → 401."""
        payload_json = json.dumps(professional_payload)
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer invalid-token",
        }

        with patch("app.core.security.verify_token", new_callable=AsyncMock) as mock_verify:
            from fastapi import HTTPException

            mock_verify.side_effect = HTTPException(status_code=401, detail="Token invalide")

            response = client.post(
                "/api/v1/professionals/",
                content=payload_json,
                headers=headers,
            )

        assert response.status_code == 401

    def test_create_professional_no_authorization(self, client, professional_payload):
        """Test création sans authentification → 401."""
        payload_json = json.dumps(professional_payload)
        headers = {
            "Content-Type": "application/json",
        }

        response = client.post(
            "/api/v1/professionals/",
            content=payload_json,
            headers=headers,
        )

        assert response.status_code == 401
        assert "Authentification requise" in response.json()["detail"]


class TestCreateProfessionalSchemaValidation:
    """Tests pour la validation des schémas Pydantic."""

    def test_create_professional_webhook_uses_correct_schema(
        self, client, professional_payload, webhook_secret
    ):
        """Test que le webhook utilise ProfessionalCreateFromWebhook avec is_active=False."""
        from datetime import UTC, datetime

        payload_json = json.dumps(professional_payload)
        headers = create_webhook_headers(payload_json, webhook_secret)

        with patch("app.core.config.settings.WEBHOOK_SECRET", webhook_secret):
            with patch("app.core.config.settings.WEBHOOK_SIGNATURE_TOLERANCE", 300):
                with patch(
                    "app.services.professional_service.create_professional",
                    new_callable=AsyncMock,
                ) as mock_create:
                    from app.models.professional import Professional

                    mock_professional = Professional(
                        id=1,
                        keycloak_user_id=professional_payload["keycloak_user_id"],
                        first_name=professional_payload["first_name"],
                        last_name=professional_payload["last_name"],
                        is_active=False,
                        is_verified=False,
                        email=professional_payload["email"],
                        phone=professional_payload["phone"],
                        specialty=professional_payload["specialty"],
                        professional_type=professional_payload["professional_type"],
                        title=professional_payload["title"],
                        is_available=True,
                        languages_spoken="fr",
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    mock_create.return_value = mock_professional

                    response = client.post(
                        "/api/v1/professionals/",
                        content=payload_json,
                        headers=headers,
                    )

                    # Vérifier que professional_data passé au service est bien
                    # de type ProfessionalCreateFromWebhook avec is_active=False
                    call_args = mock_create.call_args
                    professional_data = call_args.kwargs["professional_data"]

                    # Vérifier que is_active est False
                    assert professional_data.is_active is False

                    # Vérifier que current_user_id est None (webhook)
                    assert call_args.kwargs["current_user_id"] is None

        assert response.status_code == 201

    def test_create_professional_admin_uses_standard_schema(
        self, client, professional_payload, admin_token
    ):
        """Test que l'admin utilise ProfessionalCreate (standard)."""
        from datetime import UTC, datetime

        payload_json = json.dumps(professional_payload)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {admin_token}",
        }

        mock_token_data = {
            "sub": "admin-user-id-123",
            "realm_access": {"roles": ["admin"]},
        }

        with patch("app.core.security.verify_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_token_data

            with patch(
                "app.services.professional_service.create_professional",
                new_callable=AsyncMock,
            ) as mock_create:
                from app.models.professional import Professional

                mock_professional = Professional(
                    id=2,
                    keycloak_user_id=professional_payload["keycloak_user_id"],
                    first_name=professional_payload["first_name"],
                    last_name=professional_payload["last_name"],
                    is_active=True,
                    is_verified=False,
                    email=professional_payload["email"],
                    phone=professional_payload["phone"],
                    specialty=professional_payload["specialty"],
                    professional_type=professional_payload["professional_type"],
                    title=professional_payload["title"],
                    is_available=True,
                    languages_spoken="fr",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    created_by="admin-user-id-123",
                    updated_by="admin-user-id-123",
                )
                mock_create.return_value = mock_professional

                response = client.post(
                    "/api/v1/professionals/",
                    content=payload_json,
                    headers=headers,
                )

                # Vérifier que professional_data passé est le ProfessionalCreate standard
                call_args = mock_create.call_args
                professional_data = call_args.kwargs["professional_data"]

                # Vérifier que c'est bien ProfessionalCreate (pas FromWebhook)
                from app.schemas.professional import ProfessionalCreate

                assert isinstance(professional_data, ProfessionalCreate)

                # Vérifier que current_user_id est l'admin
                assert call_args.kwargs["current_user_id"] == "admin-user-id-123"

        assert response.status_code == 201

    def test_create_professional_duplicate_keycloak_user_id(
        self, client, professional_payload, admin_token
    ):
        """Test création avec keycloak_user_id déjà existant → 409."""
        payload_json = json.dumps(professional_payload)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {admin_token}",
        }

        mock_token_data = {
            "sub": "admin-user-id-123",
            "realm_access": {"roles": ["admin"]},
        }

        with patch("app.core.security.verify_token", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_token_data

            with patch(
                "app.services.professional_service.create_professional",
                new_callable=AsyncMock,
            ) as mock_create:
                from sqlalchemy.exc import IntegrityError

                mock_create.side_effect = IntegrityError(
                    "duplicate key", "params", "orig", connection_invalidated=False
                )

                response = client.post(
                    "/api/v1/professionals/",
                    content=payload_json,
                    headers=headers,
                )

        assert response.status_code in [409, 400]
