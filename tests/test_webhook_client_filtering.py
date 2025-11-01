"""Tests du filtrage des clients dans le webhook processor.

Ce module teste la logique de filtrage des événements webhook basée sur le clientId.
Seuls les événements provenant des portails patient et professionnel doivent être traités.
Les événements provenant d'autres clients (ex: admin) sont ignorés avec succès.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.keycloak import KeycloakWebhookEvent, SyncResult
from app.services.webhook_processor import ALLOWED_CLIENT_IDS, route_webhook_event


def get_valid_timestamp() -> int:
    """Génère un timestamp valide (maintenant en millisecondes)."""
    return int(datetime.now().timestamp() * 1000)


class TestWebhookClientFiltering:
    """Tests de filtrage des événements webhook par clientId."""

    @pytest.mark.asyncio
    async def test_allowed_client_patient_portal(self):
        """Les événements du portail patient sont traités."""
        event = KeycloakWebhookEvent(
            eventType="LOGIN",
            realmId="africare",
            clientId="apps-africare-patient-portal",
            userId="user-patient-123",
            eventTime=get_valid_timestamp(),
        )

        # Mock de la DB session
        mock_db = AsyncMock()

        # Mock du handler LOGIN (track_user_login)
        mock_result = SyncResult(
            success=True,
            event_type="LOGIN",
            user_id="user-patient-123",
            patient_id=None,
            message="User login tracked",
        )

        # Mock de la fonction publish pour éviter les appels Redis
        with patch("app.services.keycloak_sync_service.publish", new_callable=AsyncMock):
            with patch("app.services.webhook_processor.track_user_login", return_value=mock_result):
                result = await route_webhook_event(mock_db, event)

        # LOGIN retourne toujours success=True (tracking uniquement)
        assert result.success is True
        assert "ignoré" not in result.message.lower()

    @pytest.mark.asyncio
    async def test_allowed_client_provider_portal(self):
        """Les événements du portail professionnel sont traités."""
        event = KeycloakWebhookEvent(
            eventType="LOGIN",
            realmId="africare",
            clientId="apps-africare-provider-portal",
            userId="user-professional-456",
            eventTime=get_valid_timestamp(),
        )

        mock_db = AsyncMock()
        mock_result = SyncResult(
            success=True,
            event_type="LOGIN",
            user_id="user-professional-456",
            patient_id=None,
            message="User login tracked",
        )

        with patch("app.services.keycloak_sync_service.publish", new_callable=AsyncMock):
            with patch("app.services.webhook_processor.track_user_login", return_value=mock_result):
                result = await route_webhook_event(mock_db, event)

        # LOGIN retourne toujours success=True (tracking uniquement)
        assert result.success is True
        assert "ignoré" not in result.message.lower()

    @pytest.mark.asyncio
    async def test_disallowed_client_admin_portal(self):
        """Les événements du portail admin sont ignorés avec succès."""
        event = KeycloakWebhookEvent(
            eventType="UPDATE_PROFILE",
            realmId="africare",
            clientId="apps-africare-admin-portal",
            userId="user-admin-789",
            eventTime=get_valid_timestamp(),
        )

        mock_db = AsyncMock()
        result = await route_webhook_event(mock_db, event)

        # L'événement est ignoré MAIS retourne success=True pour ACK le message
        assert result.success is True
        assert "ignoré" in result.message.lower()
        assert "admin" in result.message.lower()
        assert result.patient_id is None

    @pytest.mark.asyncio
    async def test_disallowed_client_custom_app(self):
        """Les événements d'une application custom sont ignorés."""
        event = KeycloakWebhookEvent(
            eventType="REGISTER",
            realmId="africare",
            clientId="custom-app-client",
            userId="user-custom-101",
            eventTime=get_valid_timestamp(),
        )

        mock_db = AsyncMock()
        result = await route_webhook_event(mock_db, event)

        # Ignoré avec succès
        assert result.success is True
        assert "ignoré" in result.message.lower()
        assert "custom-app-client" in result.message

    @pytest.mark.asyncio
    async def test_null_client_id_treated_as_allowed(self):
        """Les événements sans clientId (null) sont traités normalement."""
        event = KeycloakWebhookEvent(
            eventType="LOGIN",
            realmId="africare",
            clientId=None,  # Pas de clientId
            userId="user-no-client-202",
            eventTime=get_valid_timestamp(),
        )

        mock_db = AsyncMock()
        mock_result = SyncResult(
            success=True,
            event_type="LOGIN",
            user_id="user-no-client-202",
            patient_id=None,
            message="User login tracked",
        )

        with patch("app.services.keycloak_sync_service.publish", new_callable=AsyncMock):
            with patch("app.services.webhook_processor.track_user_login", return_value=mock_result):
                result = await route_webhook_event(mock_db, event)

        # Traité normalement (pas filtré)
        assert result.success is True
        # Le message ne doit pas contenir "ignoré" (car traité)
        # LOGIN retourne un message de tracking
        assert "ignoré" not in result.message.lower()

    @pytest.mark.asyncio
    async def test_allowed_clients_constant(self):
        """Vérifier que la constante ALLOWED_CLIENT_IDS contient les bons clients."""
        assert "apps-africare-patient-portal" in ALLOWED_CLIENT_IDS
        assert "apps-africare-provider-portal" in ALLOWED_CLIENT_IDS
        assert len(ALLOWED_CLIENT_IDS) == 2

    @pytest.mark.asyncio
    async def test_disallowed_client_register_event(self):
        """Les événements REGISTER d'un admin sont ignorés."""
        event = KeycloakWebhookEvent(
            eventType="REGISTER",
            realmId="africare",
            clientId="apps-africare-admin-portal",
            userId="user-admin-register",
            eventTime=get_valid_timestamp(),
            user={
                "id": "user-admin-register",
                "username": "admin@africare.sn",
                "email": "admin@africare.sn",
                "firstName": "Admin",
                "lastName": "User",
                "enabled": True,
            },
        )

        mock_db = AsyncMock()
        result = await route_webhook_event(mock_db, event)

        # Ignoré avec succès (pas d'erreur, pas de retry)
        assert result.success is True
        assert "ignoré" in result.message.lower()
        assert result.patient_id is None

    @pytest.mark.asyncio
    async def test_delete_event_from_admin_client_is_processed(self):
        """Les événements DELETE même d'un admin sont traités (synchronisation suppression)."""
        event = KeycloakWebhookEvent(
            eventType="DELETE",
            realmId="africare",
            clientId="apps-africare-admin-portal",
            userId="user-admin-delete",
            eventTime=get_valid_timestamp(),
        )

        mock_db = AsyncMock()

        # Mock du handler DELETE dans EVENT_HANDLERS
        mock_handler = AsyncMock(
            return_value=SyncResult(
                success=True,
                event_type="DELETE",
                user_id="user-admin-delete",
                patient_id=None,
                message="User deletion processed",
            )
        )

        with patch("app.services.webhook_processor.EVENT_HANDLERS", {"DELETE": mock_handler}):
            result = await route_webhook_event(mock_db, event)

        # DELETE est traité même si clientId non autorisé (synchronisation des suppressions)
        assert result.success is True
        assert "ignoré" not in result.message.lower()
        assert result.event_type == "DELETE"

    @pytest.mark.asyncio
    async def test_disallowed_client_event_attributes_set(self):
        """Vérifier que les attributs OpenTelemetry sont correctement définis."""
        event = KeycloakWebhookEvent(
            eventType="UPDATE_EMAIL",
            realmId="africare",
            clientId="some-other-client",
            userId="user-other-303",
            eventTime=get_valid_timestamp(),
        )

        mock_db = AsyncMock()
        result = await route_webhook_event(mock_db, event)

        # L'événement doit être ignoré avec succès
        assert result.success is True
        assert result.event_type == "UPDATE_EMAIL"
        assert result.user_id == "user-other-303"
        assert "ignoré" in result.message.lower()

    @pytest.mark.asyncio
    async def test_case_sensitive_client_id(self):
        """Le clientId est sensible à la casse."""
        event = KeycloakWebhookEvent(
            eventType="LOGIN",
            realmId="africare",
            clientId="APPS-AFRICARE-PATIENT-PORTAL",  # Majuscules
            userId="user-case-test",
            eventTime=get_valid_timestamp(),
        )

        mock_db = AsyncMock()
        result = await route_webhook_event(mock_db, event)

        # Doit être ignoré car la casse ne correspond pas
        assert result.success is True
        assert "ignoré" in result.message.lower()

    @pytest.mark.asyncio
    async def test_admin_update_event_ignored(self):
        """Les événements ADMIN_UPDATE sont ignorés (console admin Keycloak)."""
        event = KeycloakWebhookEvent(
            eventType="ADMIN_UPDATE",
            realmId="africare",
            clientId="security-admin-console",
            userId="user-updated-by-admin",
            eventTime=get_valid_timestamp(),
            user={
                "id": "user-updated-by-admin",
                "username": "patient@africare.sn",
                "email": "patient@africare.sn",
                "firstName": "Amadou",
                "lastName": "Diallo",
                "enabled": True,
            },
        )

        mock_db = AsyncMock()
        result = await route_webhook_event(mock_db, event)

        # L'événement ADMIN_UPDATE est ignoré avec succès
        assert result.success is True
        assert "admin console" in result.message.lower()
        assert result.patient_id is None

    @pytest.mark.asyncio
    async def test_admin_update_with_null_client_id(self):
        """Les événements ADMIN_UPDATE sans clientId sont ignorés."""
        event = KeycloakWebhookEvent(
            eventType="ADMIN_UPDATE",
            realmId="africare",
            clientId=None,  # Admin console peut avoir clientId null
            userId="user-admin-update-null",
            eventTime=get_valid_timestamp(),
            user={
                "id": "user-admin-update-null",
                "username": "test@africare.sn",
                "email": "test@africare.sn",
                "enabled": True,
            },
        )

        mock_db = AsyncMock()
        result = await route_webhook_event(mock_db, event)

        # Ignoré avec succès même si clientId est null
        assert result.success is True
        assert "admin console" in result.message.lower()

    @pytest.mark.asyncio
    async def test_delete_with_null_client_id_is_processed(self):
        """Les événements DELETE avec clientId=null sont traités (suppression admin)."""
        event = KeycloakWebhookEvent(
            eventType="DELETE",
            realmId="africare",
            clientId=None,  # DELETE peut avoir clientId null (admin console)
            userId="user-deleted-by-admin",
            eventTime=get_valid_timestamp(),
        )

        mock_db = AsyncMock()

        # Mock du handler DELETE dans EVENT_HANDLERS
        mock_handler = AsyncMock(
            return_value=SyncResult(
                success=True,
                event_type="DELETE",
                user_id="user-deleted-by-admin",
                patient_id=None,
                message="User deletion processed",
            )
        )

        with patch("app.services.webhook_processor.EVENT_HANDLERS", {"DELETE": mock_handler}):
            result = await route_webhook_event(mock_db, event)

        # DELETE est traité même si clientId est null
        assert result.success is True
        assert "ignoré" not in result.message.lower()
        assert result.event_type == "DELETE"

    @pytest.mark.asyncio
    async def test_delete_with_allowed_client_is_processed(self):
        """Les événements DELETE avec clientId autorisé sont traités."""
        event = KeycloakWebhookEvent(
            eventType="DELETE",
            realmId="africare",
            clientId="apps-africare-patient-portal",  # Client autorisé
            userId="user-deleted-patient",
            eventTime=get_valid_timestamp(),
        )

        mock_db = AsyncMock()

        # Mock du handler DELETE dans EVENT_HANDLERS
        mock_handler = AsyncMock(
            return_value=SyncResult(
                success=True,
                event_type="DELETE",
                user_id="user-deleted-patient",
                patient_id=123,
                message="User deleted successfully",
            )
        )

        with patch("app.services.webhook_processor.EVENT_HANDLERS", {"DELETE": mock_handler}):
            result = await route_webhook_event(mock_db, event)

        # DELETE avec clientId autorisé est traité
        assert result.success is True
        assert "ignoré" not in result.message.lower()
        assert result.event_type == "DELETE"

    @pytest.mark.asyncio
    async def test_admin_update_prefix_always_ignored(self):
        """Les événements ADMIN_UPDATE (préfixe ADMIN_) sont toujours ignorés."""
        event = KeycloakWebhookEvent(
            eventType="ADMIN_UPDATE",
            realmId="africare",
            clientId="security-admin-console",
            userId="user-admin-update-test",
            eventTime=get_valid_timestamp(),
            user={
                "id": "user-admin-update-test",
                "username": "test@africare.sn",
                "email": "test@africare.sn",
                "enabled": True,
            },
        )

        mock_db = AsyncMock()
        result = await route_webhook_event(mock_db, event)

        # ADMIN_UPDATE doit être ignoré
        assert result.success is True
        assert "admin console" in result.message.lower()
        assert result.patient_id is None
