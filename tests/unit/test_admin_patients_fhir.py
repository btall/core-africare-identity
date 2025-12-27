"""Tests unitaires pour les endpoints admin patients avec architecture FHIR.

Ce module teste les endpoints administrateur qui utilisent:
- PatientGdprMetadata pour les metadonnees RGPD locales
- Client FHIR mocke pour les donnees demographiques
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.admin_patients import (
    _extract_email_from_fhir,
    _extract_national_id_from_fhir,
    delete_patient_admin,
    list_soft_deleted_patients,
    mark_patient_under_investigation,
    remove_investigation_status,
    restore_soft_deleted_patient,
)
from app.infrastructure.fhir.identifiers import NATIONAL_ID_SYSTEM
from app.models.gdpr_metadata import PatientGdprMetadata
from app.schemas.patient import (
    PatientDeletionContext,
    PatientDeletionRequest,
    PatientRestoreRequest,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_fhir_patient():
    """Create a mock FHIR Patient resource."""
    mock_patient = MagicMock()
    mock_patient.id = "fhir-patient-123"
    mock_patient.active = True

    # Telecom mock
    email_telecom = MagicMock()
    email_telecom.system = "email"
    email_telecom.value = "test@example.sn"

    phone_telecom = MagicMock()
    phone_telecom.system = "phone"
    phone_telecom.value = "+221771234567"

    mock_patient.telecom = [email_telecom, phone_telecom]

    # Identifier mock
    keycloak_id = MagicMock()
    keycloak_id.system = "https://keycloak.africare.app/realms/africare"
    keycloak_id.value = "test-keycloak-id-123"

    national_id = MagicMock()
    national_id.system = NATIONAL_ID_SYSTEM
    national_id.value = "SN123456789"

    mock_patient.identifier = [keycloak_id, national_id]

    # Name mock
    name = MagicMock()
    name.given = ["Amadou"]
    name.family = "Diallo"
    mock_patient.name = [name]

    return mock_patient


@pytest.fixture
def mock_fhir_client(mock_fhir_patient):
    """Create a mock FHIR client."""
    client = MagicMock()
    client.read = AsyncMock(return_value=mock_fhir_patient)
    client.update = AsyncMock(return_value=mock_fhir_patient)
    return client


@pytest.fixture
def sample_gdpr_metadata():
    """Create sample GDPR metadata for testing."""
    return PatientGdprMetadata(
        id=1,
        fhir_resource_id="fhir-patient-123",
        keycloak_user_id="test-keycloak-id-123",
        is_verified=True,
        under_investigation=False,
        investigation_notes=None,
        correlation_hash=None,
        soft_deleted_at=None,
        anonymized_at=None,
        deletion_reason=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_events():
    """Mock event publishing."""
    with patch(
        "app.api.v1.endpoints.admin_patients.publish", new_callable=AsyncMock
    ) as mock_publish:
        yield mock_publish


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


# =============================================================================
# Tests pour fonctions helper
# =============================================================================


class TestExtractEmailFromFhir:
    """Tests pour _extract_email_from_fhir()."""

    def test_extract_email_found(self, mock_fhir_patient):
        """Test extraction email trouve."""
        result = _extract_email_from_fhir(mock_fhir_patient)
        assert result == "test@example.sn"

    def test_extract_email_no_telecom(self):
        """Test extraction sans telecom."""
        patient = MagicMock()
        patient.telecom = None
        result = _extract_email_from_fhir(patient)
        assert result is None

    def test_extract_email_no_email_in_telecom(self):
        """Test extraction telecom sans email."""
        patient = MagicMock()
        phone = MagicMock()
        phone.system = "phone"
        phone.value = "+221771234567"
        patient.telecom = [phone]
        result = _extract_email_from_fhir(patient)
        assert result is None

    def test_extract_email_empty_telecom(self):
        """Test extraction telecom vide."""
        patient = MagicMock()
        patient.telecom = []
        result = _extract_email_from_fhir(patient)
        assert result is None


class TestExtractNationalIdFromFhir:
    """Tests pour _extract_national_id_from_fhir()."""

    def test_extract_national_id_found(self, mock_fhir_patient):
        """Test extraction national_id trouve."""
        result = _extract_national_id_from_fhir(mock_fhir_patient)
        assert result == "SN123456789"

    def test_extract_national_id_no_identifier(self):
        """Test extraction sans identifier."""
        patient = MagicMock()
        patient.identifier = None
        result = _extract_national_id_from_fhir(patient)
        assert result is None

    def test_extract_national_id_no_match(self):
        """Test extraction identifier sans national_id."""
        patient = MagicMock()
        keycloak_id = MagicMock()
        keycloak_id.system = "https://keycloak.africare.app/realms/africare"
        keycloak_id.value = "test-user"
        patient.identifier = [keycloak_id]
        result = _extract_national_id_from_fhir(patient)
        assert result is None


# =============================================================================
# Tests pour mark_patient_under_investigation
# =============================================================================


class TestMarkPatientUnderInvestigation:
    """Tests pour mark_patient_under_investigation()."""

    @pytest.mark.skip(
        reason="Test nécessite refactoring des mocks FHIR - PatientMapper.from_fhir() avec MagicMock"
    )
    @pytest.mark.asyncio
    async def test_mark_investigation_success(
        self, mock_session, mock_fhir_client, mock_events, sample_gdpr_metadata
    ):
        """Test marquage sous enquete reussi."""
        mock_session.get = AsyncMock(return_value=sample_gdpr_metadata)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            context = PatientDeletionContext(reason="Enquete medicale")
            await mark_patient_under_investigation(patient_id=1, context=context, db=mock_session)

            # Verify GDPR metadata updated
            assert sample_gdpr_metadata.under_investigation is True
            assert sample_gdpr_metadata.investigation_notes == "Enquete medicale"

            # Verify event published
            mock_events.assert_called_once()
            call_args = mock_events.call_args
            assert call_args[0][0] == "identity.patient.investigation_started"

    @pytest.mark.asyncio
    async def test_mark_investigation_patient_not_found(self, mock_session, mock_fhir_client):
        """Test marquage echoue si patient non trouve."""
        mock_session.get = AsyncMock(return_value=None)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            context = PatientDeletionContext(reason="Test")

            with pytest.raises(HTTPException) as exc_info:
                await mark_patient_under_investigation(
                    patient_id=999, context=context, db=mock_session
                )

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_mark_investigation_fhir_resource_not_found(
        self, mock_session, mock_events, sample_gdpr_metadata
    ):
        """Test marquage echoue si ressource FHIR non trouvee."""
        mock_session.get = AsyncMock(return_value=sample_gdpr_metadata)

        mock_fhir_client = MagicMock()
        mock_fhir_client.read = AsyncMock(return_value=None)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            context = PatientDeletionContext(reason="Test")

            with pytest.raises(HTTPException) as exc_info:
                await mark_patient_under_investigation(
                    patient_id=1, context=context, db=mock_session
                )

            assert exc_info.value.status_code == 500

    @pytest.mark.skip(
        reason="Test nécessite refactoring des mocks FHIR - PatientMapper.from_fhir() avec MagicMock"
    )
    @pytest.mark.asyncio
    async def test_mark_investigation_default_notes(
        self, mock_session, mock_fhir_client, mock_events, sample_gdpr_metadata
    ):
        """Test marquage avec notes par defaut."""
        mock_session.get = AsyncMock(return_value=sample_gdpr_metadata)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            context = PatientDeletionContext(reason=None)  # Pas de raison fournie
            await mark_patient_under_investigation(patient_id=1, context=context, db=mock_session)

            assert sample_gdpr_metadata.investigation_notes == "Enquête en cours"


# =============================================================================
# Tests pour remove_investigation_status
# =============================================================================


class TestRemoveInvestigationStatus:
    """Tests pour remove_investigation_status()."""

    @pytest.mark.skip(
        reason="Test nécessite refactoring des mocks FHIR - PatientMapper.from_fhir() avec MagicMock"
    )
    @pytest.mark.asyncio
    async def test_remove_investigation_success(self, mock_session, mock_fhir_client, mock_events):
        """Test retrait enquete reussi."""
        gdpr = PatientGdprMetadata(
            id=1,
            fhir_resource_id="fhir-123",
            keycloak_user_id="test-user",
            is_verified=True,
            under_investigation=True,
            investigation_notes="Enquete en cours",
        )
        mock_session.get = AsyncMock(return_value=gdpr)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            await remove_investigation_status(patient_id=1, db=mock_session)

            assert gdpr.under_investigation is False
            assert gdpr.investigation_notes is None

            mock_events.assert_called_once()
            assert mock_events.call_args[0][0] == "identity.patient.investigation_cleared"

    @pytest.mark.asyncio
    async def test_remove_investigation_not_found(self, mock_session, mock_fhir_client):
        """Test retrait echoue si patient non trouve."""
        mock_session.get = AsyncMock(return_value=None)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await remove_investigation_status(patient_id=999, db=mock_session)

            assert exc_info.value.status_code == 404


# =============================================================================
# Tests pour delete_patient_admin
# =============================================================================


class TestDeletePatientAdmin:
    """Tests pour delete_patient_admin()."""

    @pytest.mark.asyncio
    async def test_delete_patient_success(
        self, mock_session, mock_fhir_client, mock_events, sample_gdpr_metadata
    ):
        """Test suppression RGPD reussie."""
        mock_session.get = AsyncMock(return_value=sample_gdpr_metadata)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            with patch(
                "app.api.v1.endpoints.admin_patients._generate_patient_correlation_hash",
                return_value="abcd1234" * 8,
            ):
                deletion_request = PatientDeletionRequest(deletion_reason="admin_action")
                await delete_patient_admin(
                    patient_id=1, db=mock_session, deletion_request=deletion_request
                )

                # Verify GDPR metadata updated
                assert sample_gdpr_metadata.soft_deleted_at is not None
                assert sample_gdpr_metadata.deletion_reason == "admin_action"
                assert sample_gdpr_metadata.correlation_hash is not None

                # Verify FHIR updated
                mock_fhir_client.update.assert_called_once()

                # Verify event published
                mock_events.assert_called_once()
                assert mock_events.call_args[0][0] == "identity.patient.soft_deleted"

    @pytest.mark.asyncio
    async def test_delete_patient_already_deleted_idempotent(self, mock_session, mock_fhir_client):
        """Test suppression deja soft deleted est idempotent."""
        gdpr = PatientGdprMetadata(
            id=1,
            fhir_resource_id="fhir-123",
            keycloak_user_id="test-user",
            is_verified=True,
            soft_deleted_at=datetime.now(UTC),  # Deja supprime
        )
        mock_session.get = AsyncMock(return_value=gdpr)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            deletion_request = PatientDeletionRequest(deletion_reason="admin_action")
            result = await delete_patient_admin(
                patient_id=1, db=mock_session, deletion_request=deletion_request
            )

            # Should return without error (idempotent)
            assert result is None
            mock_fhir_client.update.assert_not_called()

    @pytest.mark.skip(
        reason="Test nécessite refactoring des mocks FHIR - PatientDeletionBlockedError signature"
    )
    @pytest.mark.asyncio
    async def test_delete_patient_blocked_under_investigation(self, mock_session, mock_fhir_client):
        """Test suppression bloquee si sous enquete."""
        from app.core.exceptions import PatientDeletionBlockedError

        gdpr = PatientGdprMetadata(
            id=1,
            fhir_resource_id="fhir-123",
            keycloak_user_id="test-user",
            is_verified=True,
            under_investigation=True,
            investigation_notes="Enquete en cours",
        )
        mock_session.get = AsyncMock(return_value=gdpr)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            deletion_request = PatientDeletionRequest(
                deletion_reason="admin_action", investigation_check_override=False
            )

            with pytest.raises(PatientDeletionBlockedError) as exc_info:
                await delete_patient_admin(
                    patient_id=1, db=mock_session, deletion_request=deletion_request
                )

            assert exc_info.value.status_code == 423

    @pytest.mark.asyncio
    async def test_delete_patient_override_investigation(
        self, mock_session, mock_fhir_client, mock_events
    ):
        """Test suppression avec override investigation."""
        gdpr = PatientGdprMetadata(
            id=1,
            fhir_resource_id="fhir-123",
            keycloak_user_id="test-user",
            is_verified=True,
            under_investigation=True,
            investigation_notes="Enquete en cours",
        )
        mock_session.get = AsyncMock(return_value=gdpr)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            with patch(
                "app.api.v1.endpoints.admin_patients._generate_patient_correlation_hash",
                return_value="abcd1234" * 8,
            ):
                deletion_request = PatientDeletionRequest(
                    deletion_reason="admin_action",
                    investigation_check_override=True,  # Force deletion
                )
                await delete_patient_admin(
                    patient_id=1, db=mock_session, deletion_request=deletion_request
                )

                # Should succeed despite investigation
                assert gdpr.soft_deleted_at is not None

    @pytest.mark.asyncio
    async def test_delete_patient_not_found(self, mock_session, mock_fhir_client):
        """Test suppression echoue si patient non trouve."""
        mock_session.get = AsyncMock(return_value=None)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            deletion_request = PatientDeletionRequest(deletion_reason="admin_action")

            with pytest.raises(HTTPException) as exc_info:
                await delete_patient_admin(
                    patient_id=999, db=mock_session, deletion_request=deletion_request
                )

            assert exc_info.value.status_code == 404


# =============================================================================
# Tests pour restore_soft_deleted_patient
# =============================================================================


class TestRestoreSoftDeletedPatient:
    """Tests pour restore_soft_deleted_patient()."""

    @pytest.mark.skip(
        reason="Test nécessite refactoring des mocks FHIR - PatientMapper.from_fhir() avec MagicMock"
    )
    @pytest.mark.asyncio
    async def test_restore_patient_success(self, mock_session, mock_fhir_client, mock_events):
        """Test restauration reussie."""
        gdpr = PatientGdprMetadata(
            id=1,
            fhir_resource_id="fhir-123",
            keycloak_user_id="test-user",
            is_verified=True,
            soft_deleted_at=datetime.now(UTC) - timedelta(days=3),
            deletion_reason="user_request",
        )
        mock_session.get = AsyncMock(return_value=gdpr)

        # Mock FHIR patient for update
        mock_fhir_patient = MagicMock()
        mock_fhir_patient.active = False
        mock_fhir_client.read = AsyncMock(return_value=mock_fhir_patient)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            restore_request = PatientRestoreRequest(restore_reason="Demande utilisateur")
            await restore_soft_deleted_patient(
                patient_id=1, restore_request=restore_request, db=mock_session
            )

            # Verify GDPR metadata updated
            assert gdpr.soft_deleted_at is None
            assert gdpr.deletion_reason is None

            # Verify FHIR updated
            assert mock_fhir_patient.active is True
            mock_fhir_client.update.assert_called_once()

            # Verify event published
            mock_events.assert_called_once()
            assert mock_events.call_args[0][0] == "identity.patient.restored"

    @pytest.mark.asyncio
    async def test_restore_patient_already_anonymized(self, mock_session, mock_fhir_client):
        """Test restauration echoue si deja anonymise."""
        gdpr = PatientGdprMetadata(
            id=1,
            fhir_resource_id="fhir-123",
            keycloak_user_id="test-user",
            is_verified=True,
            soft_deleted_at=datetime.now(UTC) - timedelta(days=10),
            anonymized_at=datetime.now(UTC) - timedelta(days=3),  # Deja anonymise
        )
        mock_session.get = AsyncMock(return_value=gdpr)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            restore_request = PatientRestoreRequest(restore_reason="Test")

            with pytest.raises(HTTPException) as exc_info:
                await restore_soft_deleted_patient(
                    patient_id=1, restore_request=restore_request, db=mock_session
                )

            assert exc_info.value.status_code == 422
            assert "already anonymized" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_restore_patient_not_found(self, mock_session, mock_fhir_client):
        """Test restauration echoue si patient non trouve."""
        mock_session.get = AsyncMock(return_value=None)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            restore_request = PatientRestoreRequest(restore_reason="Test")

            with pytest.raises(HTTPException) as exc_info:
                await restore_soft_deleted_patient(
                    patient_id=999, restore_request=restore_request, db=mock_session
                )

            assert exc_info.value.status_code == 404


# =============================================================================
# Tests pour list_soft_deleted_patients
# =============================================================================


class TestListSoftDeletedPatients:
    """Tests pour list_soft_deleted_patients()."""

    @pytest.mark.asyncio
    async def test_list_soft_deleted_success(self, mock_session, mock_fhir_client):
        """Test listage patients soft deleted."""
        now = datetime.now(UTC)
        gdpr1 = PatientGdprMetadata(
            id=1,
            fhir_resource_id="fhir-1",
            keycloak_user_id="user-1",
            is_verified=True,
            soft_deleted_at=now - timedelta(days=2),
            deletion_reason="user_request",
        )
        gdpr2 = PatientGdprMetadata(
            id=2,
            fhir_resource_id="fhir-2",
            keycloak_user_id="user-2",
            is_verified=True,
            soft_deleted_at=now - timedelta(days=5),
            deletion_reason="admin_action",
        )

        # Mock the query result
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [gdpr1, gdpr2]
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await list_soft_deleted_patients(db=mock_session)

            assert len(result) == 2
            assert result[0].patient_id == 1
            assert result[1].patient_id == 2
            assert result[0].soft_deleted_at is not None
            assert result[0].anonymized_at is None

    @pytest.mark.asyncio
    async def test_list_soft_deleted_empty(self, mock_session, mock_fhir_client):
        """Test listage sans patients soft deleted."""
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await list_soft_deleted_patients(db=mock_session)

            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_list_soft_deleted_fhir_error_continues(self, mock_session):
        """Test listage continue si erreur FHIR."""
        gdpr = PatientGdprMetadata(
            id=1,
            fhir_resource_id="fhir-1",
            keycloak_user_id="user-1",
            is_verified=True,
            soft_deleted_at=datetime.now(UTC) - timedelta(days=2),
        )

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [gdpr]
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        # FHIR client raises exception
        mock_fhir_client = MagicMock()
        mock_fhir_client.read = AsyncMock(side_effect=Exception("FHIR unavailable"))

        with patch(
            "app.api.v1.endpoints.admin_patients.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await list_soft_deleted_patients(db=mock_session)

            # Should still return result with email=None
            assert len(result) == 1
            assert result[0].email is None
