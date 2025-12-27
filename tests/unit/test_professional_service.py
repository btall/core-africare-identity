"""Tests unitaires pour professional_service.py.

Ce module teste les operations CRUD et metier du service professionnel
avec architecture hybride FHIR + PostgreSQL.
"""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.practitioner import Practitioner as FHIRPractitioner
from fhir.resources.practitioner import PractitionerQualification

from app.infrastructure.fhir.exceptions import FHIRResourceNotFoundError
from app.infrastructure.fhir.identifiers import KEYCLOAK_SYSTEM, PROFESSIONAL_LICENSE_SYSTEM
from app.models.gdpr_metadata import ProfessionalGdprMetadata
from app.schemas.professional import (
    ProfessionalCreate,
    ProfessionalSearchFilters,
    ProfessionalUpdate,
)
from app.services.professional_service import (
    _build_fhir_search_params,
    _extract_keycloak_id,
    create_professional,
    delete_professional,
    get_professional,
    get_professional_by_keycloak_id,
    get_professional_by_professional_id,
    get_professional_gdpr_metadata,
    search_professionals,
    toggle_availability,
    update_professional,
    verify_professional,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_professional_create() -> ProfessionalCreate:
    """Donnees de creation d'un professionnel complet."""
    return ProfessionalCreate(
        keycloak_user_id="kc-prof-123",
        first_name="Amadou",
        last_name="Diallo",
        date_of_birth=date(1975, 3, 15),
        gender="male",
        email="dr.diallo@hospital.sn",
        phone="+221771234567",
        title="Dr",
        specialty="Médecine générale",
        sub_specialty="Cardiologie",
        professional_id="CNOM-12345",
        professional_type="physician",
        facility_name="CHU Fann",
        facility_city="Dakar",
        facility_region="Dakar",
        preferred_language="fr",
        is_available=True,
        notes="Cardiologue experimente",
    )


@pytest.fixture
def sample_professional_update() -> ProfessionalUpdate:
    """Donnees de mise a jour professionnel."""
    return ProfessionalUpdate(
        first_name="Amadou Updated",
        sub_specialty="Pneumologie",
        is_available=False,
    )


@pytest.fixture
def sample_fhir_practitioner() -> FHIRPractitioner:
    """FHIR Practitioner pour tests."""
    return FHIRPractitioner(
        id="fhir-prac-456",
        identifier=[
            Identifier(system=KEYCLOAK_SYSTEM, value="kc-prof-123", use="official"),
            Identifier(system=PROFESSIONAL_LICENSE_SYSTEM, value="CNOM-12345", use="official"),
        ],
        active=True,
        name=[HumanName(use="official", family="Diallo", given=["Amadou"], prefix=["Dr"])],
        telecom=[
            ContactPoint(system="email", value="dr.diallo@hospital.sn", use="work"),
            ContactPoint(system="phone", value="+221771234567", use="mobile"),
        ],
        gender="male",
        birthDate="1975-03-15",
        qualification=[
            PractitionerQualification(
                code=CodeableConcept(
                    coding=[Coding(system="http://snomed.info/sct", code="physician")]
                )
            )
        ],
    )


@pytest.fixture
def sample_gdpr_metadata() -> ProfessionalGdprMetadata:
    """Metadonnees GDPR pour tests."""
    metadata = ProfessionalGdprMetadata(
        id=42,
        fhir_resource_id="fhir-prac-456",
        keycloak_user_id="kc-prof-123",
        is_verified=True,
        is_available=True,
        notes="Professionnel verifie",
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

    def test_extract_keycloak_id_found(self, sample_fhir_practitioner):
        """Test extraction keycloak_id present."""
        result = _extract_keycloak_id(sample_fhir_practitioner)
        assert result == "kc-prof-123"

    def test_extract_keycloak_id_not_found(self):
        """Test extraction sans keycloak_id."""
        practitioner = FHIRPractitioner(
            identifier=[
                Identifier(system=PROFESSIONAL_LICENSE_SYSTEM, value="CNOM-123"),
            ],
            name=[HumanName(family="Test")],
        )
        result = _extract_keycloak_id(practitioner)
        assert result is None

    def test_extract_keycloak_id_no_identifiers(self):
        """Test extraction sans identifiers."""
        practitioner = FHIRPractitioner(
            name=[HumanName(family="Test")],
        )
        result = _extract_keycloak_id(practitioner)
        assert result is None


# =============================================================================
# Tests _build_fhir_search_params
# =============================================================================


class TestBuildFhirSearchParams:
    """Tests pour _build_fhir_search_params helper."""

    def test_build_params_all_filters(self):
        """Test construction avec tous les filtres."""
        filters = ProfessionalSearchFilters(
            first_name="Amadou",
            last_name="Diallo",
            professional_id="CNOM-123",
            specialty="Cardiologie",
            facility_city="Dakar",
            facility_region="Dakar",
            is_active=True,
            limit=20,
            skip=10,
        )
        params = _build_fhir_search_params(filters)

        assert params["given"] == "Amadou"
        assert params["family"] == "Diallo"
        assert f"{PROFESSIONAL_LICENSE_SYSTEM}|CNOM-123" in params["identifier"]
        assert params["qualification-code"] == "Cardiologie"
        assert params["address-city"] == "Dakar"
        assert params["address-state"] == "Dakar"
        assert params["active"] == "true"
        assert params["_count"] == "20"
        assert params["_offset"] == "10"

    def test_build_params_minimal_filters(self):
        """Test construction avec filtres minimaux."""
        filters = ProfessionalSearchFilters()
        params = _build_fhir_search_params(filters)

        assert "given" not in params
        assert "family" not in params
        assert "identifier" not in params
        assert "_count" in params  # Pagination toujours presente
        assert "_offset" in params

    def test_build_params_is_active_false(self):
        """Test construction avec is_active=false."""
        filters = ProfessionalSearchFilters(is_active=False)
        params = _build_fhir_search_params(filters)

        assert params["active"] == "false"


# =============================================================================
# Tests create_professional
# =============================================================================


class TestCreateProfessional:
    """Tests pour create_professional."""

    @pytest.mark.asyncio
    async def test_create_professional_success(
        self,
        sample_professional_create,
        sample_fhir_practitioner,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test creation reussie d'un professionnel."""
        # Configure mocks
        mock_fhir_client.create.return_value = sample_fhir_practitioner

        # Mock la metadonnee GDPR creee
        mock_gdpr = MagicMock()
        mock_gdpr.id = 42
        mock_gdpr.fhir_resource_id = "fhir-prac-456"
        mock_gdpr.keycloak_user_id = "kc-prof-123"
        mock_gdpr.is_verified = False
        mock_gdpr.is_available = True
        mock_gdpr.to_dict.return_value = {
            "is_verified": False,
            "is_available": True,
            "notes": "Cardiologue experimente",
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
            "created_by": "admin-001",
            "updated_by": "admin-001",
        }

        # Configurer db.refresh pour mettre a jour les attributs
        async def refresh_gdpr(obj):
            obj.id = 42
            obj.fhir_resource_id = "fhir-prac-456"

        mock_db_session.refresh.side_effect = refresh_gdpr

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.professional_service.publish") as mock_publish,
            patch(
                "app.services.professional_service.ProfessionalGdprMetadata",
                return_value=mock_gdpr,
            ),
            patch("app.services.professional_service.ProfessionalMapper.to_fhir") as mock_to_fhir,
            patch(
                "app.services.professional_service.ProfessionalMapper.from_fhir"
            ) as mock_from_fhir,
        ):
            mock_to_fhir.return_value = sample_fhir_practitioner
            mock_from_fhir.return_value = MagicMock(id=42)

            await create_professional(
                mock_db_session,
                sample_professional_create,
                "admin-001",
            )

            # Verifier appels
            mock_fhir_client.create.assert_called_once()
            mock_db_session.add.assert_called_once()
            mock_db_session.commit.assert_called_once()
            mock_publish.assert_called_once()

            # Verifier evenement publie
            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.professional.created"
            assert "professional_id" in call_args[0][1]


# =============================================================================
# Tests get_professional
# =============================================================================


class TestGetProfessional:
    """Tests pour get_professional."""

    @pytest.mark.asyncio
    async def test_get_professional_found(
        self,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recuperation professionnel existant."""
        # Mock la requete DB
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_practitioner

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.services.professional_service.ProfessionalMapper.from_fhir"
            ) as mock_from_fhir,
        ):
            mock_response = MagicMock()
            mock_response.id = 42
            mock_from_fhir.return_value = mock_response

            result = await get_professional(mock_db_session, 42)

            assert result is not None
            assert result.id == 42
            mock_fhir_client.read.assert_called_once_with(
                "Practitioner", sample_gdpr_metadata.fhir_resource_id
            )

    @pytest.mark.asyncio
    async def test_get_professional_not_found_local(self, mock_db_session):
        """Test professionnel non trouve localement."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.professional_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await get_professional(mock_db_session, 999)

            assert result is None

    @pytest.mark.asyncio
    async def test_get_professional_not_found_fhir(
        self,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test professionnel trouve localement mais pas dans FHIR."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = None

        with patch(
            "app.services.professional_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_professional(mock_db_session, 42)

            assert result is None


# =============================================================================
# Tests get_professional_by_keycloak_id
# =============================================================================


class TestGetProfessionalByKeycloakId:
    """Tests pour get_professional_by_keycloak_id."""

    @pytest.mark.asyncio
    async def test_get_by_keycloak_id_found(
        self,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recuperation par keycloak_user_id."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_practitioner

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.services.professional_service.ProfessionalMapper.from_fhir"
            ) as mock_from_fhir,
        ):
            mock_response = MagicMock()
            mock_response.id = 42
            mock_from_fhir.return_value = mock_response

            result = await get_professional_by_keycloak_id(mock_db_session, "kc-prof-123")

            assert result is not None
            assert result.id == 42

    @pytest.mark.asyncio
    async def test_get_by_keycloak_id_not_found(self, mock_db_session):
        """Test professionnel non trouve par keycloak_id."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.professional_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await get_professional_by_keycloak_id(mock_db_session, "unknown-kc-id")

            assert result is None


# =============================================================================
# Tests get_professional_by_professional_id
# =============================================================================


class TestGetProfessionalByProfessionalId:
    """Tests pour get_professional_by_professional_id."""

    @pytest.mark.asyncio
    async def test_get_by_professional_id_found(
        self,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recuperation par numero d'ordre professionnel."""
        mock_fhir_client.search_by_identifier.return_value = sample_fhir_practitioner

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.services.professional_service.ProfessionalMapper.from_fhir"
            ) as mock_from_fhir,
        ):
            mock_response = MagicMock()
            mock_response.id = 42
            mock_from_fhir.return_value = mock_response

            result = await get_professional_by_professional_id(mock_db_session, "CNOM-12345")

            assert result is not None
            mock_fhir_client.search_by_identifier.assert_called_once_with(
                "Practitioner", PROFESSIONAL_LICENSE_SYSTEM, "CNOM-12345"
            )

    @pytest.mark.asyncio
    async def test_get_by_professional_id_not_found_fhir(
        self,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test professionnel non trouve dans FHIR."""
        mock_fhir_client.search_by_identifier.return_value = None

        with patch(
            "app.services.professional_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_professional_by_professional_id(mock_db_session, "UNKNOWN-123")

            assert result is None


# =============================================================================
# Tests update_professional
# =============================================================================


class TestUpdateProfessional:
    """Tests pour update_professional."""

    @pytest.mark.asyncio
    async def test_update_professional_success(
        self,
        sample_professional_update,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test mise a jour reussie."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_practitioner
        mock_fhir_client.update.return_value = sample_fhir_practitioner

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.professional_service.publish") as mock_publish,
            patch(
                "app.services.professional_service.ProfessionalMapper.apply_updates"
            ) as mock_apply,
            patch(
                "app.services.professional_service.ProfessionalMapper.from_fhir"
            ) as mock_from_fhir,
        ):
            mock_apply.return_value = sample_fhir_practitioner
            mock_response = MagicMock()
            mock_response.id = 42
            mock_from_fhir.return_value = mock_response

            result = await update_professional(
                mock_db_session,
                42,
                sample_professional_update,
                "admin-001",
            )

            assert result is not None
            mock_fhir_client.update.assert_called_once()
            mock_publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_professional_not_found(
        self,
        sample_professional_update,
        mock_db_session,
    ):
        """Test mise a jour professionnel non trouve."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.professional_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await update_professional(
                mock_db_session,
                999,
                sample_professional_update,
                "admin-001",
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_update_professional_fhir_error(
        self,
        sample_professional_update,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test mise a jour avec erreur FHIR."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_practitioner
        mock_fhir_client.update.side_effect = FHIRResourceNotFoundError(
            "Practitioner", "fhir-prac-456"
        )

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.services.professional_service.ProfessionalMapper.apply_updates"
            ) as mock_apply,
        ):
            mock_apply.return_value = sample_fhir_practitioner

            result = await update_professional(
                mock_db_session,
                42,
                sample_professional_update,
                "admin-001",
            )

            assert result is None


# =============================================================================
# Tests delete_professional
# =============================================================================


class TestDeleteProfessional:
    """Tests pour delete_professional."""

    @pytest.mark.asyncio
    async def test_delete_professional_success(
        self,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test soft delete reussi."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_practitioner
        mock_fhir_client.update.return_value = sample_fhir_practitioner

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.professional_service.publish") as mock_publish,
        ):
            result = await delete_professional(
                mock_db_session,
                42,
                "admin-001",
                deletion_reason="user_request",
            )

            assert result is True
            assert sample_gdpr_metadata.soft_deleted_at is not None
            mock_db_session.commit.assert_called_once()
            mock_publish.assert_called_once()

            # Verifier l'evenement
            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.professional.deactivated"

    @pytest.mark.asyncio
    async def test_delete_professional_not_found(
        self,
        mock_db_session,
    ):
        """Test delete professionnel non trouve."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.professional_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await delete_professional(mock_db_session, 999, "admin-001")

            assert result is False

    @pytest.mark.asyncio
    async def test_delete_professional_under_investigation(
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
            "app.services.professional_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await delete_professional(mock_db_session, 42, "admin-001")

            assert result is False
            mock_db_session.commit.assert_not_called()


# =============================================================================
# Tests search_professionals
# =============================================================================


class TestSearchProfessionals:
    """Tests pour search_professionals."""

    @pytest.mark.asyncio
    async def test_search_professionals_success(
        self,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recherche reussie."""
        # Mock bundle FHIR avec resultats
        mock_entry = MagicMock()
        mock_entry.resource = sample_fhir_practitioner

        mock_bundle = MagicMock()
        mock_bundle.entry = [mock_entry]
        mock_bundle.total = 1

        mock_fhir_client.search.return_value = mock_bundle

        # Mock query locale
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_gdpr_metadata]
        mock_db_session.execute.return_value = mock_result

        filters = ProfessionalSearchFilters(first_name="Amadou", limit=10)

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.services.professional_service.ProfessionalMapper.to_list_item"
            ) as mock_to_list,
        ):
            mock_item = MagicMock()
            mock_item.id = 42
            mock_to_list.return_value = mock_item

            items, total = await search_professionals(mock_db_session, filters)

            assert len(items) == 1
            assert total == 1

    @pytest.mark.asyncio
    async def test_search_professionals_empty_results(
        self,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recherche sans resultats."""
        mock_bundle = MagicMock()
        mock_bundle.entry = None
        mock_bundle.total = 0

        mock_fhir_client.search.return_value = mock_bundle

        filters = ProfessionalSearchFilters(first_name="InexistantNom")

        with patch(
            "app.services.professional_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            items, total = await search_professionals(mock_db_session, filters)

            assert items == []
            assert total == 0

    @pytest.mark.asyncio
    async def test_search_professionals_with_local_filters(
        self,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test recherche avec filtres locaux (is_verified, is_available)."""
        mock_entry = MagicMock()
        mock_entry.resource = sample_fhir_practitioner

        mock_bundle = MagicMock()
        mock_bundle.entry = [mock_entry]
        mock_bundle.total = 1

        mock_fhir_client.search.return_value = mock_bundle

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_gdpr_metadata]
        mock_db_session.execute.return_value = mock_result

        filters = ProfessionalSearchFilters(is_verified=True, is_available=True)

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.services.professional_service.ProfessionalMapper.to_list_item"
            ) as mock_to_list,
        ):
            mock_item = MagicMock()
            mock_to_list.return_value = mock_item

            items, total = await search_professionals(mock_db_session, filters)

            # Total = len(items) quand filtres locaux actifs
            assert total == len(items)


# =============================================================================
# Tests verify_professional
# =============================================================================


class TestVerifyProfessional:
    """Tests pour verify_professional."""

    @pytest.mark.asyncio
    async def test_verify_professional_success(
        self,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test verification reussie."""
        sample_gdpr_metadata.is_verified = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_practitioner

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.professional_service.publish") as mock_publish,
            patch(
                "app.services.professional_service.ProfessionalMapper.from_fhir"
            ) as mock_from_fhir,
        ):
            mock_response = MagicMock()
            mock_response.id = 42
            mock_response.is_verified = True
            mock_from_fhir.return_value = mock_response

            result = await verify_professional(mock_db_session, 42, "admin-001")

            assert result is not None
            assert sample_gdpr_metadata.is_verified is True
            mock_publish.assert_called_once()

            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.professional.verified"

    @pytest.mark.asyncio
    async def test_verify_professional_not_found(
        self,
        mock_db_session,
    ):
        """Test verification professionnel non trouve."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.professional_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await verify_professional(mock_db_session, 999, "admin-001")

            assert result is None


# =============================================================================
# Tests toggle_availability
# =============================================================================


class TestToggleAvailability:
    """Tests pour toggle_availability."""

    @pytest.mark.asyncio
    async def test_toggle_availability_to_unavailable(
        self,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test changement de disponibilite vers indisponible."""
        sample_gdpr_metadata.is_available = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_practitioner

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.professional_service.publish") as mock_publish,
            patch(
                "app.services.professional_service.ProfessionalMapper.from_fhir"
            ) as mock_from_fhir,
        ):
            mock_response = MagicMock()
            mock_response.id = 42
            mock_response.is_available = False
            mock_from_fhir.return_value = mock_response

            result = await toggle_availability(mock_db_session, 42, False, "prof-001")

            assert result is not None
            assert sample_gdpr_metadata.is_available is False
            mock_publish.assert_called_once()

            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.professional.availability_changed"
            assert call_args[0][1]["is_available"] is False

    @pytest.mark.asyncio
    async def test_toggle_availability_to_available(
        self,
        sample_fhir_practitioner,
        sample_gdpr_metadata,
        mock_fhir_client,
        mock_db_session,
    ):
        """Test changement de disponibilite vers disponible."""
        sample_gdpr_metadata.is_available = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        mock_fhir_client.read.return_value = sample_fhir_practitioner

        with (
            patch(
                "app.services.professional_service.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch("app.services.professional_service.publish"),
            patch(
                "app.services.professional_service.ProfessionalMapper.from_fhir"
            ) as mock_from_fhir,
        ):
            mock_response = MagicMock()
            mock_response.id = 42
            mock_response.is_available = True
            mock_from_fhir.return_value = mock_response

            result = await toggle_availability(mock_db_session, 42, True, "prof-001")

            assert result is not None
            assert sample_gdpr_metadata.is_available is True

    @pytest.mark.asyncio
    async def test_toggle_availability_not_found(
        self,
        mock_db_session,
    ):
        """Test toggle professionnel non trouve."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.professional_service.get_fhir_client",
            return_value=MagicMock(),
        ):
            result = await toggle_availability(mock_db_session, 999, True, "prof-001")

            assert result is None


# =============================================================================
# Tests get_professional_gdpr_metadata
# =============================================================================


class TestGetProfessionalGdprMetadata:
    """Tests pour get_professional_gdpr_metadata."""

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

        result = await get_professional_gdpr_metadata(mock_db_session, 42)

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

        result = await get_professional_gdpr_metadata(mock_db_session, 999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_gdpr_metadata_includes_deleted(
        self,
        sample_gdpr_metadata,
        mock_db_session,
    ):
        """Test recuperation inclut les professionnels supprimes (pour admin)."""
        sample_gdpr_metadata.soft_deleted_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_gdpr_metadata
        mock_db_session.execute.return_value = mock_result

        result = await get_professional_gdpr_metadata(mock_db_session, 42)

        # get_professional_gdpr_metadata n'a pas de filtre soft_deleted_at
        assert result is not None
        assert result.soft_deleted_at is not None
