"""Tests unitaires pour patient_service.py.

Ce module teste les operations CRUD et metier du service patient
avec architecture hybride FHIR + PostgreSQL.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fhir.resources.address import Address as FHIRAddress
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.patient import Patient as FHIRPatient

from app.infrastructure.fhir.exceptions import FHIRResourceNotFoundError
from app.infrastructure.fhir.identifiers import KEYCLOAK_SYSTEM, NATIONAL_ID_SYSTEM
from app.models.gdpr_metadata import PatientGdprMetadata
from app.schemas.patient import (
    PatientCreate,
    PatientSearchFilters,
    PatientUpdate,
)
from app.services.patient_service import (
    _build_fhir_search_params,
    _extract_keycloak_id,
    create_patient,
    delete_patient,
    get_patient,
    get_patient_by_keycloak_id,
    get_patient_by_national_id,
    get_patient_gdpr_metadata,
    search_patients,
    update_patient,
    verify_patient,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_patient_create() -> PatientCreate:
    """Donnees de creation d'un patient complet."""
    return PatientCreate(
        keycloak_user_id="kc-patient-123",
        national_id="SN1234567890",
        first_name="Amadou",
        last_name="Diallo",
        date_of_birth=date(1990, 5, 15),
        gender="male",
        email="amadou.diallo@example.sn",
        phone="+221771234567",
        address_line1="123 Rue de la Paix",
        city="Dakar",
        region="Dakar",
        country="Senegal",
        preferred_language="fr",
    )


@pytest.fixture
def sample_patient_update() -> PatientUpdate:
    """Donnees de mise a jour patient."""
    return PatientUpdate(
        first_name="Amadou Updated",
        city="Saint-Louis",
    )


@pytest.fixture
def sample_fhir_patient() -> FHIRPatient:
    """FHIR Patient pour tests."""
    return FHIRPatient(
        id="fhir-pat-456",
        identifier=[
            Identifier(system=KEYCLOAK_SYSTEM, value="kc-patient-123", use="official"),
            Identifier(system=NATIONAL_ID_SYSTEM, value="SN1234567890", use="official"),
        ],
        active=True,
        name=[HumanName(use="official", family="Diallo", given=["Amadou"])],
        telecom=[
            ContactPoint(system="email", value="amadou.diallo@example.sn", use="home"),
            ContactPoint(system="phone", value="+221771234567", use="mobile"),
        ],
        gender="male",
        birthDate="1990-05-15",
        address=[
            FHIRAddress(
                use="home",
                city="Dakar",
                state="Dakar",
                country="Senegal",
            )
        ],
    )


@pytest.fixture
def sample_gdpr_metadata() -> PatientGdprMetadata:
    """Metadonnees GDPR pour tests."""
    metadata = PatientGdprMetadata(
        id=42,
        fhir_resource_id="fhir-pat-456",
        keycloak_user_id="kc-patient-123",
        is_verified=True,
        notes="Patient verifie",
        under_investigation=False,
        soft_deleted_at=None,
        anonymized_at=None,
        created_by="admin-001",
        updated_by="admin-001",
        created_at=datetime(2024, 1, 15, 10, 0, 0),
        updated_at=datetime(2024, 6, 20, 14, 0, 0),
    )
    return metadata


@pytest.fixture
def mock_fhir_client():
    """Mock du client FHIR."""
    client = MagicMock()
    client.create = AsyncMock()
    client.read = AsyncMock()
    client.update = AsyncMock()
    client.search = AsyncMock()
    client.search_by_identifier = AsyncMock()
    return client


@pytest.fixture
def mock_db_session():
    """Mock de la session de base de donnees."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    return session


# =============================================================================
# Tests _extract_keycloak_id
# =============================================================================


class TestExtractKeycloakId:
    """Tests pour _extract_keycloak_id helper."""

    def test_extract_keycloak_id_found(self, sample_fhir_patient):
        """Test extraction keycloak_id present."""
        result = _extract_keycloak_id(sample_fhir_patient)
        assert result == "kc-patient-123"

    def test_extract_keycloak_id_not_found(self):
        """Test extraction sans keycloak_id."""
        patient = FHIRPatient(
            identifier=[
                Identifier(system=NATIONAL_ID_SYSTEM, value="SN123"),
            ],
            name=[HumanName(family="Test")],
            gender="male",
            birthDate="2000-01-01",
        )
        result = _extract_keycloak_id(patient)
        assert result is None

    def test_extract_keycloak_id_no_identifiers(self):
        """Test extraction sans identifiers."""
        patient = FHIRPatient(
            name=[HumanName(family="Test")],
            gender="male",
            birthDate="2000-01-01",
        )
        result = _extract_keycloak_id(patient)
        assert result is None


# =============================================================================
# Tests _build_fhir_search_params
# =============================================================================


class TestBuildFhirSearchParams:
    """Tests pour _build_fhir_search_params helper."""

    def test_build_params_all_filters(self):
        """Test construction avec tous les filtres."""
        filters = PatientSearchFilters(
            first_name="Amadou",
            last_name="Diallo",
            national_id="SN123",
            email="test@example.com",
            phone="+221771234567",
            gender="male",
            is_active=True,
            city="Dakar",
            region="Dakar",
            limit=20,
            skip=10,
        )
        params = _build_fhir_search_params(filters)

        assert params["given"] == "Amadou"
        assert params["family"] == "Diallo"
        assert f"{NATIONAL_ID_SYSTEM}|SN123" in params["identifier"]
        assert params["email"] == "test@example.com"
        assert params["phone"] == "+221771234567"
        assert params["gender"] == "male"
        assert params["active"] == "true"
        assert params["address-city"] == "Dakar"
        assert params["address-state"] == "Dakar"
        assert params["_count"] == "20"
        assert params["_offset"] == "10"

    def test_build_params_minimal_filters(self):
        """Test construction avec filtres minimaux."""
        filters = PatientSearchFilters()
        params = _build_fhir_search_params(filters)

        assert "given" not in params
        assert "family" not in params
        assert "identifier" not in params
        assert "_count" in params  # Pagination toujours presente
        assert "_offset" in params

    def test_build_params_is_active_false(self):
        """Test construction avec is_active=false."""
        filters = PatientSearchFilters(is_active=False)
        params = _build_fhir_search_params(filters)

        assert params["active"] == "false"


# =============================================================================
# Tests create_patient
# =============================================================================


class TestCreatePatient:
    """Tests pour create_patient."""

    @pytest.mark.asyncio
    async def test_create_patient_success(
        self,
        sample_patient_create,
        sample_fhir_patient,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test creation reussie d'un patient."""
        mock_fhir_client.create.return_value = sample_fhir_patient

        mock_gdpr = MagicMock()
        mock_gdpr.id = 42
        mock_gdpr.fhir_resource_id = "fhir-pat-456"
        mock_gdpr.keycloak_user_id = "kc-patient-123"
        mock_gdpr.is_verified = False
        mock_gdpr.to_dict.return_value = {
            "is_verified": False,
            "notes": None,
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
            "created_by": "admin-001",
            "updated_by": "admin-001",
        }

        async def refresh_gdpr(obj):
            obj.id = 42
            obj.fhir_resource_id = "fhir-pat-456"

        mock_db_session.refresh.side_effect = refresh_gdpr

        with (
            patch(
                "app.services.patient_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.patient_service.publish") as mock_publish,
            patch(
                "app.services.patient_service.PatientGdprMetadata",
                return_value=mock_gdpr,
            ),
            patch("app.services.patient_service.PatientMapper.to_fhir") as mock_to_fhir,
            patch("app.services.patient_service.PatientMapper.from_fhir") as mock_from_fhir,
        ):
            mock_to_fhir.return_value = sample_fhir_patient
            mock_from_fhir.return_value = MagicMock(id=42)

            await create_patient(
                mock_db_session,
                sample_patient_create,
                "admin-001",
            )

            mock_fhir_client.create.assert_called_once()
            mock_db_session.add.assert_called_once()
            mock_db_session.commit.assert_called_once()
            mock_publish.assert_called_once()

            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.patient.created"


# =============================================================================
# Tests get_patient
# =============================================================================


class TestGetPatient:
    """Tests pour get_patient."""

    @pytest.mark.asyncio
    async def test_get_patient_found(
        self,
        sample_fhir_patient,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recuperation patient existant."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_patient

        with (
            patch(
                "app.services.patient_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.patient_service.PatientMapper.from_fhir") as mock_from_fhir,
        ):
            mock_response = MagicMock()
            mock_response.id = 42
            mock_from_fhir.return_value = mock_response

            result = await get_patient(mock_db_session, 42)

            assert result is not None
            assert result.id == 42
            mock_fhir_client.read.assert_called_once_with(
                "Patient", sample_gdpr_metadata.fhir_resource_id
            )

    @pytest.mark.asyncio
    async def test_get_patient_not_found_local(self, mock_db_session):
        """Test patient non trouve localement."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.patient_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await get_patient(mock_db_session, 999)

            assert result is None

    @pytest.mark.asyncio
    async def test_get_patient_not_found_fhir(
        self,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test patient trouve localement mais pas dans FHIR."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = None

        with patch(
            "app.services.patient_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_patient(mock_db_session, 42)

            assert result is None


# =============================================================================
# Tests get_patient_by_keycloak_id
# =============================================================================


class TestGetPatientByKeycloakId:
    """Tests pour get_patient_by_keycloak_id."""

    @pytest.mark.asyncio
    async def test_get_by_keycloak_id_found(
        self,
        sample_fhir_patient,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recuperation par keycloak_user_id."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_patient

        with (
            patch(
                "app.services.patient_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.patient_service.PatientMapper.from_fhir") as mock_from_fhir,
        ):
            mock_response = MagicMock()
            mock_response.id = 42
            mock_from_fhir.return_value = mock_response

            result = await get_patient_by_keycloak_id(mock_db_session, "kc-patient-123")

            assert result is not None
            assert result.id == 42

    @pytest.mark.asyncio
    async def test_get_by_keycloak_id_not_found(self, mock_db_session):
        """Test patient non trouve par keycloak_id."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.patient_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await get_patient_by_keycloak_id(mock_db_session, "unknown-kc-id")

            assert result is None


# =============================================================================
# Tests get_patient_by_national_id
# =============================================================================


class TestGetPatientByNationalId:
    """Tests pour get_patient_by_national_id."""

    @pytest.mark.asyncio
    async def test_get_by_national_id_found(
        self,
        sample_fhir_patient,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recuperation par identifiant national."""
        mock_fhir_client.search_by_identifier.return_value = sample_fhir_patient

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        with (
            patch(
                "app.services.patient_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.patient_service.PatientMapper.from_fhir") as mock_from_fhir,
        ):
            mock_response = MagicMock()
            mock_response.id = 42
            mock_from_fhir.return_value = mock_response

            result = await get_patient_by_national_id(mock_db_session, "SN1234567890")

            assert result is not None
            mock_fhir_client.search_by_identifier.assert_called_once_with(
                "Patient", NATIONAL_ID_SYSTEM, "SN1234567890"
            )

    @pytest.mark.asyncio
    async def test_get_by_national_id_not_found_fhir(
        self,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test patient non trouve dans FHIR."""
        mock_fhir_client.search_by_identifier.return_value = None

        with patch(
            "app.services.patient_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_patient_by_national_id(mock_db_session, "UNKNOWN-123")

            assert result is None


# =============================================================================
# Tests update_patient
# =============================================================================


class TestUpdatePatient:
    """Tests pour update_patient."""

    @pytest.mark.asyncio
    async def test_update_patient_success(
        self,
        sample_patient_update,
        sample_fhir_patient,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test mise a jour reussie."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_patient
        mock_fhir_client.update.return_value = sample_fhir_patient

        with (
            patch(
                "app.services.patient_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.patient_service.publish") as mock_publish,
            patch("app.services.patient_service.PatientMapper.apply_updates") as mock_apply,
            patch("app.services.patient_service.PatientMapper.from_fhir") as mock_from_fhir,
        ):
            mock_apply.return_value = sample_fhir_patient
            mock_response = MagicMock()
            mock_response.id = 42
            mock_from_fhir.return_value = mock_response

            result = await update_patient(
                mock_db_session,
                42,
                sample_patient_update,
                "admin-001",
            )

            assert result is not None
            mock_fhir_client.update.assert_called_once()
            mock_publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_patient_not_found(
        self,
        sample_patient_update,
        mock_db_session,
    ):
        """Test mise a jour patient non trouve."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.patient_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await update_patient(
                mock_db_session,
                999,
                sample_patient_update,
                "admin-001",
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_update_patient_fhir_error(
        self,
        sample_patient_update,
        sample_fhir_patient,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test mise a jour avec erreur FHIR."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_patient
        mock_fhir_client.update.side_effect = FHIRResourceNotFoundError("Patient", "fhir-pat-456")

        with (
            patch(
                "app.services.patient_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.patient_service.PatientMapper.apply_updates") as mock_apply,
        ):
            mock_apply.return_value = sample_fhir_patient

            result = await update_patient(
                mock_db_session,
                42,
                sample_patient_update,
                "admin-001",
            )

            assert result is None


# =============================================================================
# Tests delete_patient
# =============================================================================


class TestDeletePatient:
    """Tests pour delete_patient."""

    @pytest.mark.asyncio
    async def test_delete_patient_success(
        self,
        sample_fhir_patient,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test soft delete reussi."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_patient
        mock_fhir_client.update.return_value = sample_fhir_patient

        with (
            patch(
                "app.services.patient_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.patient_service.publish") as mock_publish,
        ):
            result = await delete_patient(
                mock_db_session,
                42,
                "admin-001",
                deletion_reason="user_request",
            )

            assert result is True
            assert sample_gdpr_metadata.soft_deleted_at is not None
            mock_db_session.commit.assert_called_once()
            mock_publish.assert_called_once()

            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.patient.deactivated"

    @pytest.mark.asyncio
    async def test_delete_patient_not_found(
        self,
        mock_db_session,
    ):
        """Test delete patient non trouve."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.patient_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await delete_patient(mock_db_session, 999, "admin-001")

            assert result is False

    @pytest.mark.asyncio
    async def test_delete_patient_under_investigation(
        self,
        sample_gdpr_metadata,
        mock_db_session,
    ):
        """Test delete bloque si sous enquete."""
        sample_gdpr_metadata.under_investigation = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.patient_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await delete_patient(mock_db_session, 42, "admin-001")

            assert result is False
            mock_db_session.commit.assert_not_called()


# =============================================================================
# Tests search_patients
# =============================================================================


class TestSearchPatients:
    """Tests pour search_patients."""

    @pytest.mark.asyncio
    async def test_search_patients_success(
        self,
        sample_fhir_patient,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recherche reussie."""
        mock_entry = MagicMock()
        mock_entry.resource = sample_fhir_patient

        mock_bundle = MagicMock()
        mock_bundle.entry = [mock_entry]
        mock_bundle.total = 1

        mock_fhir_client.search.return_value = mock_bundle

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_gdpr_metadata]
        mock_db_session.execute.return_value = mock_result

        filters = PatientSearchFilters(first_name="Amadou", limit=10)

        with (
            patch(
                "app.services.patient_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.patient_service.PatientMapper.to_list_item") as mock_to_list,
        ):
            mock_item = MagicMock()
            mock_item.id = 42
            mock_to_list.return_value = mock_item

            items, total = await search_patients(mock_db_session, filters)

            assert len(items) == 1
            assert total == 1

    @pytest.mark.asyncio
    async def test_search_patients_empty_results(
        self,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recherche sans resultats."""
        mock_bundle = MagicMock()
        mock_bundle.entry = None
        mock_bundle.total = 0

        mock_fhir_client.search.return_value = mock_bundle

        filters = PatientSearchFilters(first_name="InexistantNom")

        with patch(
            "app.services.patient_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            items, total = await search_patients(mock_db_session, filters)

            assert items == []
            assert total == 0


# =============================================================================
# Tests verify_patient
# =============================================================================


class TestVerifyPatient:
    """Tests pour verify_patient."""

    @pytest.mark.asyncio
    async def test_verify_patient_success(
        self,
        sample_gdpr_metadata,
        mock_db_session,
    ):
        """Test verification reussie."""
        sample_gdpr_metadata.is_verified = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        with patch("app.services.patient_service.publish") as mock_publish:
            result = await verify_patient(mock_db_session, 42, "admin-001")

            # verify_patient retourne None apres mise a jour
            assert result is None
            assert sample_gdpr_metadata.is_verified is True
            mock_publish.assert_called_once()

            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.patient.verified"

    @pytest.mark.asyncio
    async def test_verify_patient_not_found(
        self,
        mock_db_session,
    ):
        """Test verification patient non trouve."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await verify_patient(mock_db_session, 999, "admin-001")

        assert result is None


# =============================================================================
# Tests get_patient_gdpr_metadata
# =============================================================================


class TestGetPatientGdprMetadata:
    """Tests pour get_patient_gdpr_metadata."""

    @pytest.mark.asyncio
    async def test_get_gdpr_metadata_found(
        self,
        sample_gdpr_metadata,
        mock_db_session,
    ):
        """Test recuperation metadonnees GDPR."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        result = await get_patient_gdpr_metadata(mock_db_session, 42)

        assert result is not None
        assert result.id == 42
        assert result.is_verified is True

    @pytest.mark.asyncio
    async def test_get_gdpr_metadata_not_found(
        self,
        mock_db_session,
    ):
        """Test metadonnees GDPR non trouvees."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await get_patient_gdpr_metadata(mock_db_session, 999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_gdpr_metadata_includes_deleted(
        self,
        sample_gdpr_metadata,
        mock_db_session,
    ):
        """Test recuperation inclut les patients supprimes (pour admin)."""
        sample_gdpr_metadata.soft_deleted_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        result = await get_patient_gdpr_metadata(mock_db_session, 42)

        # get_patient_gdpr_metadata n'a pas de filtre soft_deleted_at
        assert result is not None
        assert result.soft_deleted_at is not None
