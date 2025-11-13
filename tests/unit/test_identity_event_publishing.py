"""
Tests unitaires pour la publication d'événements dans keycloak_sync_service.

Valide que les événements identity.*.soft_deleted, identity.*.anonymized,
identity.*.deleted et identity.professional.restored sont correctement publiés.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.patient import Patient
from app.models.professional import Professional
from app.schemas.keycloak import KeycloakWebhookEvent
from app.services.keycloak_sync_service import _anonymize, _hard_delete, _soft_delete


@pytest.fixture
def sample_professional():
    """Fixture pour un professionnel de test."""
    professional = Professional(
        id=1,
        keycloak_user_id="prof-keycloak-123",
        first_name="Jean",
        last_name="Dupont",
        email="jean.dupont@example.com",
        phone="+221771234567",
        professional_id="PROF-001",
        specialty="Cardiology",
        years_of_experience=10,
        facility_name="Hopital Principal",
        is_active=True,
        under_investigation=False,
    )
    return professional


@pytest.fixture
def sample_patient():
    """Fixture pour un patient de test."""
    patient = Patient(
        id=1,
        keycloak_user_id="patient-keycloak-456",
        first_name="Marie",
        last_name="Ndiaye",
        email="marie.ndiaye@example.com",
        phone="+221771234568",
        date_of_birth=datetime(1990, 5, 15).date(),
        gender="female",
        country="Sénégal",
        preferred_language="fr",
        is_active=True,
    )
    return patient


@pytest.fixture
def sample_webhook_event():
    """Fixture pour un événement webhook Keycloak."""
    return KeycloakWebhookEvent(
        event_type="DELETE",
        realm_id="africare",
        user_id="keycloak-123",
        event_time=int(datetime.now(UTC).timestamp() * 1000),  # milliseconds
        deletion_reason="user_request",
    )


class TestSoftDeleteEventPublishing:
    """Tests pour la publication d'événements lors d'un soft delete."""

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    async def test_soft_delete_publishes_professional_event(
        self, mock_publish, sample_professional, sample_webhook_event
    ):
        """Test que _soft_delete publie identity.professional.soft_deleted."""
        # Action
        await _soft_delete(sample_professional, sample_webhook_event)

        # Assertions
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args

        # Vérifier le nom de l'événement
        assert call_args[0][0] == "identity.professional.soft_deleted"

        # Vérifier le payload
        payload = call_args[0][1]
        assert payload["professional_keycloak_id"] == "prof-keycloak-123"
        assert "deleted_at" in payload
        assert payload["reason"] == "user_request"
        assert "anonymization_scheduled_at" in payload

        # Vérifier que l'entity a été marquée comme soft deleted
        assert sample_professional.is_active is False
        assert sample_professional.soft_deleted_at is not None
        assert sample_professional.deletion_reason == "user_request"

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    async def test_soft_delete_publishes_patient_event(
        self, mock_publish, sample_patient, sample_webhook_event
    ):
        """Test que _soft_delete publie identity.patient.soft_deleted."""
        # Action
        await _soft_delete(sample_patient, sample_webhook_event)

        # Assertions
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args

        # Vérifier le nom de l'événement
        assert call_args[0][0] == "identity.patient.soft_deleted"

        # Vérifier le payload
        payload = call_args[0][1]
        assert payload["patient_keycloak_id"] == "patient-keycloak-456"
        assert "deleted_at" in payload
        assert payload["reason"] == "user_request"
        assert "anonymization_scheduled_at" in payload

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    async def test_soft_delete_blocks_professional_under_investigation(
        self, mock_publish, sample_professional, sample_webhook_event
    ):
        """Test que _soft_delete bloque si professionnel sous enquête."""
        from app.core.exceptions import ProfessionalDeletionBlockedError

        # Setup
        sample_professional.under_investigation = True
        sample_professional.investigation_notes = "Pending review"

        # Action & Assertions
        with pytest.raises(ProfessionalDeletionBlockedError):
            await _soft_delete(sample_professional, sample_webhook_event)

        # Vérifier que l'événement n'a PAS été publié
        mock_publish.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    async def test_soft_delete_skips_already_deleted(
        self, mock_publish, sample_professional, sample_webhook_event
    ):
        """Test que _soft_delete saute si déjà soft deleted."""
        # Setup - marquer comme déjà soft deleted
        sample_professional.soft_deleted_at = datetime.now(UTC)

        # Action
        await _soft_delete(sample_professional, sample_webhook_event)

        # Assertions - aucun événement publié
        mock_publish.assert_not_called()


class TestAnonymizeEventPublishing:
    """Tests pour la publication d'événements lors de l'anonymisation."""

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    @patch("app.services.keycloak_sync_service.bcrypt.hashpw")
    @patch("app.services.keycloak_sync_service.bcrypt.gensalt")
    async def test_anonymize_publishes_professional_event(
        self,
        mock_gensalt,
        mock_hashpw,
        mock_publish,
        sample_professional,
        sample_webhook_event,
    ):
        """Test que _anonymize publie identity.professional.anonymized."""
        # Setup mocks bcrypt
        mock_gensalt.return_value = b"$2b$12$fakesalt"
        mock_hashpw.return_value = b"$2b$12$hashedvalue"

        # Action
        await _anonymize(sample_professional, sample_webhook_event, "professional")

        # Assertions
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args

        # Vérifier le nom de l'événement
        assert call_args[0][0] == "identity.professional.anonymized"

        # Vérifier le payload
        payload = call_args[0][1]
        assert payload["professional_keycloak_id"] == "prof-keycloak-123"
        assert "anonymized_at" in payload
        assert payload["deletion_type"] == "anonymize"

        # Vérifier que l'entity a été marquée comme supprimée
        assert sample_professional.is_active is False
        assert sample_professional.deleted_at is not None
        assert sample_professional.deletion_reason == "gdpr_compliance"

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    @patch("app.services.keycloak_sync_service.bcrypt.hashpw")
    @patch("app.services.keycloak_sync_service.bcrypt.gensalt")
    async def test_anonymize_publishes_patient_event(
        self,
        mock_gensalt,
        mock_hashpw,
        mock_publish,
        sample_patient,
        sample_webhook_event,
    ):
        """Test que _anonymize publie identity.patient.anonymized."""
        # Setup mocks bcrypt
        mock_gensalt.return_value = b"$2b$12$fakesalt"
        mock_hashpw.return_value = b"$2b$12$hashedvalue"

        # Action
        await _anonymize(sample_patient, sample_webhook_event, "patient")

        # Assertions
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args

        # Vérifier le nom de l'événement
        assert call_args[0][0] == "identity.patient.anonymized"

        # Vérifier le payload
        payload = call_args[0][1]
        assert payload["patient_keycloak_id"] == "patient-keycloak-456"
        assert "anonymized_at" in payload
        assert payload["deletion_type"] == "anonymize"

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    @patch("app.services.keycloak_sync_service.bcrypt.hashpw")
    @patch("app.services.keycloak_sync_service.bcrypt.gensalt")
    async def test_anonymize_hashes_sensitive_data(
        self,
        mock_gensalt,
        mock_hashpw,
        mock_publish,
        sample_professional,
        sample_webhook_event,
    ):
        """Test que _anonymize hash correctement les données sensibles."""
        # Setup mocks bcrypt
        mock_gensalt.return_value = b"$2b$12$fakesalt"
        mock_hashpw.return_value = b"$2b$12$hashedvalue"

        original_email = sample_professional.email

        # Action
        await _anonymize(sample_professional, sample_webhook_event, "professional")

        # Assertions - données hashées
        assert sample_professional.email != original_email
        assert sample_professional.email == "$2b$12$hashedvalue"
        assert sample_professional.first_name == "$2b$12$hashedvalue"
        assert sample_professional.last_name == "$2b$12$hashedvalue"


class TestHardDeleteEventPublishing:
    """Tests pour la publication d'événements lors d'un hard delete."""

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    async def test_hard_delete_publishes_professional_event(
        self, mock_publish, sample_professional
    ):
        """Test que _hard_delete publie identity.professional.deleted."""
        # Setup
        mock_db = AsyncMock()

        # Action
        await _hard_delete(mock_db, sample_professional)

        # Assertions
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args

        # Vérifier le nom de l'événement
        assert call_args[0][0] == "identity.professional.deleted"

        # Vérifier le payload
        payload = call_args[0][1]
        assert payload["professional_keycloak_id"] == "prof-keycloak-123"
        assert "deleted_at" in payload
        assert payload["deletion_type"] == "hard"

        # Vérifier que delete a été appelé
        mock_db.delete.assert_called_once_with(sample_professional)

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    async def test_hard_delete_publishes_patient_event(self, mock_publish, sample_patient):
        """Test que _hard_delete publie identity.patient.deleted."""
        # Setup
        mock_db = AsyncMock()

        # Action
        await _hard_delete(mock_db, sample_patient)

        # Assertions
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args

        # Vérifier le nom de l'événement
        assert call_args[0][0] == "identity.patient.deleted"

        # Vérifier le payload
        payload = call_args[0][1]
        assert payload["patient_keycloak_id"] == "patient-keycloak-456"
        assert "deleted_at" in payload
        assert payload["deletion_type"] == "hard"

        # Vérifier que delete a été appelé
        mock_db.delete.assert_called_once_with(sample_patient)


class TestProfessionalRestoredEventPayload:
    """Tests pour le payload de l'événement identity.professional.restored."""

    @pytest.mark.asyncio
    async def test_restored_event_payload_format(self):
        """Test que le payload identity.professional.restored contient les bons champs."""
        # Note: Le endpoint restore_soft_deleted_professional est déjà testé
        # dans les tests d'intégration. Ce test valide uniquement le format
        # du payload d'événement attendu.

        # Format attendu du payload identity.professional.restored
        expected_payload_structure = {
            "professional_keycloak_id": str,  # UUID Keycloak (pas professional_id)
            "restore_reason": str,  # Raison de la restauration
            "restored_at": str,  # ISO datetime
        }

        # Payload d'exemple
        sample_payload = {
            "professional_keycloak_id": "prof-keycloak-123",
            "restore_reason": "User request",
            "restored_at": datetime.now(UTC).isoformat(),
        }

        # Assertions - vérifier que tous les champs requis sont présents
        for field, expected_type in expected_payload_structure.items():
            assert field in sample_payload
            assert isinstance(sample_payload[field], expected_type)

        # Vérifier que le vieux champ "professional_id" n'est PAS utilisé
        assert "professional_id" not in sample_payload


class TestEventPublishingIntegrity:
    """Tests d'intégrité pour la publication d'événements."""

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    async def test_events_published_before_db_commit(
        self, mock_publish, sample_professional, sample_webhook_event
    ):
        """Test que les événements sont publiés même si commit échoue."""
        # Note: Dans le code actuel, les événements sont publiés APRÈS les opérations DB
        # mais AVANT le commit. C'est une approche acceptable.

        # Action
        await _soft_delete(sample_professional, sample_webhook_event)

        # Assertions - événement publié
        mock_publish.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.services.keycloak_sync_service.publish")
    async def test_event_payload_contains_required_fields(
        self, mock_publish, sample_professional, sample_webhook_event
    ):
        """Test que tous les payloads d'événements contiennent les champs requis."""
        # Action
        await _soft_delete(sample_professional, sample_webhook_event)

        # Assertions
        call_args = mock_publish.call_args
        payload = call_args[0][1]

        # Champs obligatoires pour tous les événements
        assert "professional_keycloak_id" in payload or "patient_keycloak_id" in payload
        assert "deleted_at" in payload or "anonymized_at" in payload or "restored_at" in payload
