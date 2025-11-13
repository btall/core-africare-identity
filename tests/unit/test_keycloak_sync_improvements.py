"""Tests unitaires pour les améliorations de keycloak_sync_service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AnonymizationError, KeycloakServiceError
from app.models.patient import Patient
from app.models.professional import Professional
from app.schemas.keycloak import KeycloakWebhookEvent
from app.services.keycloak_sync_service import (
    _anonymize,
    get_user_roles_from_keycloak,
    sync_user_registration,
)


class TestGetUserRolesFromKeycloak:
    """Tests pour get_user_roles_from_keycloak (problème #1 CRITIQUE)."""

    @pytest.mark.asyncio
    async def test_get_user_roles_raises_on_keycloak_error(self):
        """Test que les erreurs Keycloak sont propagées (pas masquées)."""
        user_id = "test-user-123"

        with patch("app.services.keycloak_sync_service.keycloak_admin") as mock_keycloak:
            # Simuler erreur Keycloak
            mock_keycloak.get_realm_roles_of_user.side_effect = Exception(
                "Keycloak connection timeout"
            )

            # Devrait raise KeycloakServiceError au lieu de retourner []
            with pytest.raises(KeycloakServiceError) as exc_info:
                await get_user_roles_from_keycloak(user_id)

            assert "Keycloak" in str(exc_info.value)
            assert user_id in str(exc_info.value) or "Cannot retrieve roles" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_user_roles_success_returns_roles(self):
        """Test succès récupération rôles."""
        user_id = "test-user-456"

        with patch("app.services.keycloak_sync_service.keycloak_admin") as mock_keycloak:
            # Mock rôles realm
            mock_keycloak.get_realm_roles_of_user.return_value = [
                {"name": "patient"},
                {"name": "user"},
            ]

            # Mock rôles client
            mock_keycloak.get_client_id.return_value = "client-123"
            mock_keycloak.get_client_roles_of_user.return_value = [
                {"name": "read"},
            ]

            roles = await get_user_roles_from_keycloak(user_id)

            assert "patient" in roles
            assert "user" in roles
            assert "read" in roles
            assert len(roles) == 3


class TestAnonymization:
    """Tests pour _anonymize (problème #2 CRITIQUE)."""

    @pytest.mark.asyncio
    async def test_anonymize_patient_hashes_sensitive_data(self):
        """Test que l'anonymisation chiffre les données sensibles."""
        # Créer un patient avec données réelles
        patient = Patient(
            id=123,
            keycloak_user_id="user-789",
            first_name="Amadou",
            last_name="Diallo",
            email="amadou.diallo@example.sn",
            phone="+221771234567",
            national_id="1234567890123",
            date_of_birth="1990-01-01",
            gender="male",
            country="Sénégal",
            preferred_language="fr",
        )

        event = MagicMock(spec=KeycloakWebhookEvent)
        event.user_id = "user-789"

        # Mock publish() pour éviter l'erreur Redis
        with patch("app.services.keycloak_sync_service.publish"):
            await _anonymize(patient, event, "patient")

        # Les données NE DOIVENT PAS être en clair
        assert not patient.first_name.startswith("ANONYME_")  # Devrait être hashé
        assert not patient.last_name.startswith("PATIENT_")  # Devrait être hashé
        assert not patient.email.startswith("deleted_")  # Devrait être hashé

        # Vérifier que c'est un hash valide (bcrypt ou similaire)
        # Bcrypt commence par $2b$ ou $2a$ ou $2y$
        assert (
            patient.first_name.startswith("$2") or len(patient.first_name) == 60  # Longueur bcrypt
        )

        # Autres champs doivent être None (pas de données en clair)
        # Phone utilise placeholder car NOT NULL pour Professional
        assert patient.phone == "+ANONYMIZED"
        assert patient.national_id is None

        # Marqueurs RGPD OK
        assert patient.is_active is False
        assert patient.deleted_at is not None
        assert patient.deletion_reason == "gdpr_compliance"

    @pytest.mark.asyncio
    async def test_anonymize_professional_hashes_sensitive_data(self):
        """Test anonymisation professional avec chiffrement."""
        professional = Professional(
            id=456,
            keycloak_user_id="user-pro-123",
            first_name="Dr. Fatou",
            last_name="Sow",
            email="fatou.sow@clinic.sn",
            phone="+221771111111",
            professional_id="MED12345",
            title="Dr",
            specialty="Cardiology",
            professional_type="physician",
            facility_name="Clinique Dakar",
            facility_city="Dakar",
            facility_region="Dakar",
            languages_spoken="fr",
        )

        event = MagicMock(spec=KeycloakWebhookEvent)
        event.user_id = "user-pro-123"

        # Mock publish() pour éviter l'erreur Redis
        with patch("app.services.keycloak_sync_service.publish"):
            await _anonymize(professional, event, "professional")

        # Vérifier hash (pas en clair)
        assert professional.first_name.startswith("$2") or len(professional.first_name) == 60
        assert professional.last_name.startswith("$2") or len(professional.last_name) == 60

        # Données supprimées
        # Phone utilise placeholder car NOT NULL pour Professional
        assert professional.phone == "+ANONYMIZED"
        assert professional.professional_id is None

        # Marqueurs RGPD
        assert professional.is_active is False
        assert professional.deletion_reason == "gdpr_compliance"

    @pytest.mark.asyncio
    async def test_anonymize_raises_on_hash_failure(self):
        """Test que l'anonymisation lève AnonymizationError en cas d'échec."""
        patient = Patient(
            id=999,
            keycloak_user_id="user-error",
            first_name="Test",
            last_name="User",
            email="test@example.com",
            date_of_birth="1990-01-01",
            gender="male",
            country="Test",
            preferred_language="fr",
        )

        event = MagicMock(spec=KeycloakWebhookEvent)
        event.user_id = "user-error"

        # Simuler échec bcrypt
        with patch("app.services.keycloak_sync_service.bcrypt.hashpw") as mock_hash:
            mock_hash.side_effect = Exception("Hashing failed")

            with pytest.raises(AnonymizationError) as exc_info:
                await _anonymize(patient, event, "patient")

            assert "anonymiz" in str(exc_info.value).lower()


class TestSyncUserRegistration:
    """Tests pour sync_user_registration (problème #7 IMPORTANT)."""

    @pytest.mark.asyncio
    async def test_profile_type_determined_by_roles_and_client_id(self):
        """Test que le type de profil est déterminé par rôles Keycloak ET client_id."""
        db = AsyncMock(spec=AsyncSession)

        # Mock: aucun utilisateur existant (correct async mock)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        # Event avec client_id patient MAIS rôle professional
        event = MagicMock(spec=KeycloakWebhookEvent)
        event.event_type = "REGISTER"
        event.user_id = "user-ambiguous"
        event.client_id = "apps-africare-patient-portal"  # Client patient
        event.user = MagicMock()
        event.user.first_name = "Test"
        event.user.last_name = "Professional"
        event.user.email = "test@example.com"

        # Mock get_user_roles_from_keycloak pour retourner "professional"
        with patch("app.services.keycloak_sync_service.get_user_roles_from_keycloak") as mock_roles:
            mock_roles.return_value = ["professional", "user"]

            # Le service devrait créer un Professional (pas un Patient)
            # Car les rôles Keycloak ont priorité sur client_id

            with patch(
                "app.services.keycloak_sync_service._create_professional_from_event"
            ) as mock_create_pro:
                with patch(
                    "app.services.keycloak_sync_service._create_patient_from_event"
                ) as mock_create_pat:
                    mock_create_pro.return_value = MagicMock(id=123)
                    mock_create_pat.return_value = MagicMock(id=456)

                    with patch("app.services.keycloak_sync_service.publish"):
                        result = await sync_user_registration(db, event)

                    # Doit avoir créé Professional (pas Patient)
                    mock_create_pro.assert_called_once()
                    mock_create_pat.assert_not_called()

                    assert result.success is True

    @pytest.mark.asyncio
    async def test_patient_created_when_no_professional_role(self):
        """Test qu'un Patient est créé quand pas de rôle professional."""
        db = AsyncMock(spec=AsyncSession)

        # Mock: aucun utilisateur existant (correct async mock)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        event = MagicMock(spec=KeycloakWebhookEvent)
        event.event_type = "REGISTER"
        event.user_id = "user-patient"
        event.client_id = "apps-africare-patient-portal"
        event.user = MagicMock()
        event.user.first_name = "Amadou"
        event.user.last_name = "Diallo"
        event.user.email = "amadou@example.sn"

        with patch("app.services.keycloak_sync_service.get_user_roles_from_keycloak") as mock_roles:
            mock_roles.return_value = ["patient", "user"]  # Pas de "professional"

            with patch(
                "app.services.keycloak_sync_service._create_patient_from_event"
            ) as mock_create:
                mock_create.return_value = MagicMock(id=789)

                with patch("app.services.keycloak_sync_service.publish"):
                    result = await sync_user_registration(db, event)

                mock_create.assert_called_once()
                assert result.success is True
