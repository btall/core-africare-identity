"""Tests unitaires pour le service de statistiques.

Ce module teste les fonctions du service statistics_service qui agrège
les statistiques des patients et professionnels depuis FHIR et PostgreSQL.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gdpr_metadata import PatientGdprMetadata, ProfessionalGdprMetadata
from app.schemas.statistics import (
    DashboardStatistics,
    PatientStatistics,
    ProfessionalStatistics,
)
from app.services.statistics_service import (
    _get_fhir_count,
    get_dashboard_statistics,
    get_patient_statistics,
    get_professional_statistics,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_fhir_client():
    """Mock du client FHIR."""
    client = MagicMock()
    client.search = AsyncMock()
    return client


@pytest.fixture
def mock_bundle():
    """Mock d'un Bundle FHIR avec total."""
    bundle = MagicMock()
    bundle.total = 10
    return bundle


# =============================================================================
# Tests pour _get_fhir_count
# =============================================================================


class TestGetFhirCount:
    """Tests pour _get_fhir_count helper."""

    @pytest.mark.asyncio
    async def test_get_fhir_count_success(self, mock_fhir_client, mock_bundle):
        """Teste la recuperation du count FHIR avec succes."""
        mock_bundle.total = 42
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await _get_fhir_count("Patient", {"active": "true"})

        assert result == 42
        mock_fhir_client.search.assert_called_once_with(
            "Patient", {"active": "true", "_summary": "count"}
        )

    @pytest.mark.asyncio
    async def test_get_fhir_count_with_none_total(self, mock_fhir_client):
        """Teste quand bundle.total est None."""
        mock_bundle = MagicMock()
        mock_bundle.total = None
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await _get_fhir_count("Patient")

        assert result == 0

    @pytest.mark.asyncio
    async def test_get_fhir_count_exception_returns_zero(self, mock_fhir_client):
        """Teste le fallback a zero en cas d'erreur FHIR."""
        mock_fhir_client.search.side_effect = Exception("FHIR server error")

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await _get_fhir_count("Patient", {"active": "true"})

        assert result == 0

    @pytest.mark.asyncio
    async def test_get_fhir_count_no_params(self, mock_fhir_client, mock_bundle):
        """Teste l'appel sans parametres."""
        mock_bundle.total = 5
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await _get_fhir_count("Practitioner")

        assert result == 5
        mock_fhir_client.search.assert_called_once_with("Practitioner", {"_summary": "count"})


# =============================================================================
# Tests pour get_patient_statistics
# =============================================================================


class TestGetPatientStatistics:
    """Tests pour get_patient_statistics."""

    @pytest.mark.asyncio
    async def test_get_patient_statistics_fhir_success(
        self, db_session: AsyncSession, mock_fhir_client
    ):
        """Teste les stats patients quand FHIR repond."""
        # Setup: Create test GDPR metadata
        gdpr1 = PatientGdprMetadata(
            fhir_resource_id="fhir-patient-1",
            keycloak_user_id="kc-user-1",
            is_verified=True,
        )
        gdpr2 = PatientGdprMetadata(
            fhir_resource_id="fhir-patient-2",
            keycloak_user_id="kc-user-2",
            is_verified=False,
        )
        db_session.add(gdpr1)
        db_session.add(gdpr2)
        await db_session.commit()

        # Mock FHIR responses
        async def mock_search(resource_type, params):
            bundle = MagicMock()
            if resource_type == "Patient":
                if params.get("gender") == "male":
                    bundle.total = 5
                elif params.get("gender") == "female":
                    bundle.total = 3
                elif params.get("gender") == "other":
                    bundle.total = 0
                elif params.get("gender") == "unknown":
                    bundle.total = 0
                else:
                    bundle.total = 10  # total
            return bundle

        mock_fhir_client.search = AsyncMock(side_effect=mock_search)

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_patient_statistics(db_session)

        assert isinstance(result, PatientStatistics)
        assert result.total_patients == 10
        assert result.active_patients == 10
        assert result.verified_patients == 1  # Only gdpr1
        assert result.unverified_patients == 9  # 10 - 1
        assert result.patients_by_gender == {"male": 5, "female": 3}

    @pytest.mark.asyncio
    async def test_get_patient_statistics_fhir_fallback(
        self, db_session: AsyncSession, mock_fhir_client
    ):
        """Teste le fallback GDPR quand FHIR echoue."""
        # Setup: Create GDPR metadata
        gdpr1 = PatientGdprMetadata(
            fhir_resource_id="fhir-1",
            keycloak_user_id="kc-1",
            is_verified=True,
        )
        gdpr2 = PatientGdprMetadata(
            fhir_resource_id="fhir-2",
            keycloak_user_id="kc-2",
            is_verified=False,
        )
        gdpr3 = PatientGdprMetadata(
            fhir_resource_id="fhir-3",
            keycloak_user_id="kc-3",
            is_verified=False,
            soft_deleted_at=datetime.now(UTC),  # Deleted, should not count
        )
        db_session.add(gdpr1)
        db_session.add(gdpr2)
        db_session.add(gdpr3)
        await db_session.commit()

        # Mock FHIR to return 0 (simulating failure)
        mock_bundle = MagicMock()
        mock_bundle.total = 0
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_patient_statistics(db_session)

        assert result.total_patients == 2  # gdpr1 + gdpr2 (not gdpr3)
        assert result.verified_patients == 1


# =============================================================================
# Tests pour get_professional_statistics
# =============================================================================


class TestGetProfessionalStatistics:
    """Tests pour get_professional_statistics."""

    @pytest.mark.asyncio
    async def test_get_professional_statistics_fhir_success(
        self, db_session: AsyncSession, mock_fhir_client
    ):
        """Teste les stats professionnels quand FHIR repond."""
        # Setup: Create GDPR metadata
        gdpr1 = ProfessionalGdprMetadata(
            fhir_resource_id="fhir-practitioner-1",
            keycloak_user_id="kc-pro-1",
            is_verified=True,
            is_available=True,
        )
        gdpr2 = ProfessionalGdprMetadata(
            fhir_resource_id="fhir-practitioner-2",
            keycloak_user_id="kc-pro-2",
            is_verified=False,
            is_available=False,
        )
        db_session.add(gdpr1)
        db_session.add(gdpr2)
        await db_session.commit()

        # Mock FHIR to return count
        mock_bundle = MagicMock()
        mock_bundle.total = 15
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_professional_statistics(db_session)

        assert isinstance(result, ProfessionalStatistics)
        assert result.total_professionals == 15
        assert result.active_professionals == 15
        assert result.verified_professionals == 1
        assert result.unverified_professionals == 14  # 15 - 1
        assert result.available_professionals == 1
        assert result.professionals_by_type == {}  # Not implemented yet
        assert result.professionals_by_specialty == {}  # Not implemented yet

    @pytest.mark.asyncio
    async def test_get_professional_statistics_fhir_fallback(
        self, db_session: AsyncSession, mock_fhir_client
    ):
        """Teste le fallback GDPR quand FHIR echoue."""
        # Setup: Create GDPR metadata
        gdpr1 = ProfessionalGdprMetadata(
            fhir_resource_id="fhir-1",
            keycloak_user_id="kc-1",
            is_verified=True,
            is_available=True,
        )
        gdpr2 = ProfessionalGdprMetadata(
            fhir_resource_id="fhir-2",
            keycloak_user_id="kc-2",
            is_verified=True,
            is_available=True,
        )
        gdpr3 = ProfessionalGdprMetadata(
            fhir_resource_id="fhir-3",
            keycloak_user_id="kc-3",
            is_verified=False,
            is_available=False,
            anonymized_at=datetime.now(UTC),  # Anonymized, should not count
        )
        db_session.add(gdpr1)
        db_session.add(gdpr2)
        db_session.add(gdpr3)
        await db_session.commit()

        # Mock FHIR to return 0
        mock_bundle = MagicMock()
        mock_bundle.total = 0
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_professional_statistics(db_session)

        assert result.total_professionals == 2  # gdpr1 + gdpr2
        assert result.verified_professionals == 2
        assert result.available_professionals == 2


# =============================================================================
# Tests pour get_dashboard_statistics
# =============================================================================


class TestGetDashboardStatistics:
    """Tests pour get_dashboard_statistics."""

    @pytest.mark.asyncio
    async def test_get_dashboard_statistics_fhir_success(
        self, db_session: AsyncSession, mock_fhir_client
    ):
        """Teste les stats dashboard quand FHIR repond."""

        # Mock FHIR to return counts
        async def mock_search(resource_type, params):
            bundle = MagicMock()
            if resource_type == "Patient":
                bundle.total = 100
            elif resource_type == "Practitioner":
                bundle.total = 25
            return bundle

        mock_fhir_client.search = AsyncMock(side_effect=mock_search)

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_dashboard_statistics(db_session)

        assert isinstance(result, DashboardStatistics)
        assert result.total_patients == 100
        assert result.active_patients == 100
        assert result.inactive_patients == 0
        assert result.total_professionals == 25
        assert result.active_professionals == 25
        assert result.inactive_professionals == 0
        assert result.last_updated is not None

    @pytest.mark.asyncio
    async def test_get_dashboard_statistics_fhir_fallback_both(
        self, db_session: AsyncSession, mock_fhir_client
    ):
        """Teste le fallback GDPR pour patients ET professionnels."""
        # Setup: Create GDPR metadata
        for i in range(5):
            db_session.add(
                PatientGdprMetadata(
                    fhir_resource_id=f"fhir-patient-{i}",
                    keycloak_user_id=f"kc-patient-{i}",
                    is_verified=False,
                )
            )
        for i in range(3):
            db_session.add(
                ProfessionalGdprMetadata(
                    fhir_resource_id=f"fhir-pro-{i}",
                    keycloak_user_id=f"kc-pro-{i}",
                    is_verified=False,
                    is_available=True,
                )
            )
        await db_session.commit()

        # Mock FHIR to always return 0
        mock_bundle = MagicMock()
        mock_bundle.total = 0
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_dashboard_statistics(db_session)

        assert result.total_patients == 5
        assert result.active_patients == 5
        assert result.total_professionals == 3
        assert result.active_professionals == 3

    @pytest.mark.asyncio
    async def test_get_dashboard_statistics_fhir_partial_fallback(
        self, db_session: AsyncSession, mock_fhir_client
    ):
        """Teste le fallback GDPR pour patients seulement."""
        # Setup: Create GDPR metadata
        for i in range(7):
            db_session.add(
                PatientGdprMetadata(
                    fhir_resource_id=f"fhir-patient-{i}",
                    keycloak_user_id=f"kc-patient-{i}",
                    is_verified=False,
                )
            )
        await db_session.commit()

        # Mock FHIR - Patient returns 0, Practitioner returns 50
        async def mock_search(resource_type, params):
            bundle = MagicMock()
            if resource_type == "Patient":
                bundle.total = 0  # Fallback to GDPR
            elif resource_type == "Practitioner":
                bundle.total = 50  # FHIR success
            return bundle

        mock_fhir_client.search = AsyncMock(side_effect=mock_search)

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_dashboard_statistics(db_session)

        assert result.total_patients == 7  # From GDPR fallback
        assert result.total_professionals == 50  # From FHIR

    @pytest.mark.asyncio
    async def test_get_dashboard_statistics_excludes_deleted(
        self, db_session: AsyncSession, mock_fhir_client
    ):
        """Teste que les entites supprimees/anonymisees sont exclues."""
        # Create mixed GDPR data
        db_session.add(
            PatientGdprMetadata(
                fhir_resource_id="active-1",
                keycloak_user_id="kc-1",
                is_verified=False,
            )
        )
        db_session.add(
            PatientGdprMetadata(
                fhir_resource_id="deleted-1",
                keycloak_user_id="kc-2",
                is_verified=False,
                soft_deleted_at=datetime.now(UTC),
            )
        )
        db_session.add(
            PatientGdprMetadata(
                fhir_resource_id="anonymized-1",
                keycloak_user_id="kc-3",
                is_verified=False,
                anonymized_at=datetime.now(UTC),
            )
        )
        await db_session.commit()

        # Mock FHIR to return 0 (trigger fallback)
        mock_bundle = MagicMock()
        mock_bundle.total = 0
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_dashboard_statistics(db_session)

        # Only active-1 should be counted
        assert result.total_patients == 1


# =============================================================================
# Tests edge cases
# =============================================================================


class TestEdgeCases:
    """Tests pour les cas limites."""

    @pytest.mark.asyncio
    async def test_empty_database_fhir_success(self, db_session: AsyncSession, mock_fhir_client):
        """Teste avec base vide mais FHIR repond."""
        mock_bundle = MagicMock()
        mock_bundle.total = 0
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_dashboard_statistics(db_session)

        assert result.total_patients == 0
        assert result.total_professionals == 0

    @pytest.mark.asyncio
    async def test_patient_stats_all_verified(self, db_session: AsyncSession, mock_fhir_client):
        """Teste quand tous les patients sont verifies."""
        for i in range(10):
            db_session.add(
                PatientGdprMetadata(
                    fhir_resource_id=f"fhir-{i}",
                    keycloak_user_id=f"kc-{i}",
                    is_verified=True,
                )
            )
        await db_session.commit()

        # Mock FHIR to return 10
        mock_bundle = MagicMock()
        mock_bundle.total = 10
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_patient_statistics(db_session)

        assert result.total_patients == 10
        assert result.verified_patients == 10
        assert result.unverified_patients == 0

    @pytest.mark.asyncio
    async def test_professional_stats_none_available(
        self, db_session: AsyncSession, mock_fhir_client
    ):
        """Teste quand aucun professionnel n'est disponible."""
        for i in range(5):
            db_session.add(
                ProfessionalGdprMetadata(
                    fhir_resource_id=f"fhir-{i}",
                    keycloak_user_id=f"kc-{i}",
                    is_verified=True,
                    is_available=False,
                )
            )
        await db_session.commit()

        mock_bundle = MagicMock()
        mock_bundle.total = 5
        mock_fhir_client.search.return_value = mock_bundle

        with patch(
            "app.services.statistics_service.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await get_professional_statistics(db_session)

        assert result.total_professionals == 5
        assert result.verified_professionals == 5
        assert result.available_professionals == 0
