"""Tests unitaires pour endpoints admin_professionals.

Ce module teste les endpoints administrateur pour gestion avancée des professionnels:
- Investigation status management
- Restore soft deleted professionals
- List soft deleted professionals
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.practitioner import Practitioner as FHIRPractitioner
from fhir.resources.practitioner import PractitionerQualification

from app.api.v1.endpoints.admin_professionals import (
    _extract_email_from_fhir,
    _extract_keycloak_id_from_fhir,
    list_soft_deleted_professionals,
    mark_professional_under_investigation,
    remove_investigation_status,
    restore_soft_deleted_professional,
)
from app.infrastructure.fhir.identifiers import KEYCLOAK_SYSTEM
from app.models.gdpr_metadata import ProfessionalGdprMetadata
from app.schemas.professional import (
    ProfessionalDeletionContext,
    ProfessionalRestoreRequest,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_fhir_practitioner():
    """Crée un FHIRPractitioner mock pour les tests."""
    return FHIRPractitioner(
        id="fhir-123",
        active=True,
        identifier=[
            Identifier(system=KEYCLOAK_SYSTEM, value="keycloak-user-123"),
        ],
        name=[HumanName(family="Diallo", given=["Amadou"], prefix=["Dr."])],
        telecom=[
            ContactPoint(system="email", value="amadou@hospital.sn"),
            ContactPoint(system="phone", value="+221771234567"),
        ],
        qualification=[
            PractitionerQualification(
                code=CodeableConcept(
                    coding=[
                        Coding(
                            system="http://africare.app/fhir/specialty",
                            display="Médecine Générale",
                        )
                    ]
                )
            ),
            PractitionerQualification(
                code=CodeableConcept(
                    coding=[
                        Coding(
                            system="http://africare.app/fhir/professional-type",
                            code="physician",
                        )
                    ]
                )
            ),
        ],
    )


@pytest.fixture
def mock_gdpr_metadata():
    """Crée un ProfessionalGdprMetadata mock."""
    gdpr = MagicMock(spec=ProfessionalGdprMetadata)
    gdpr.id = 1
    gdpr.fhir_resource_id = "fhir-123"
    gdpr.keycloak_user_id = "keycloak-user-123"
    gdpr.under_investigation = False
    gdpr.investigation_notes = None
    gdpr.soft_deleted_at = None
    gdpr.anonymized_at = None
    gdpr.deletion_reason = None
    gdpr.is_verified = True
    gdpr.is_available = True
    gdpr.digital_signature = None
    gdpr.notes = None
    gdpr.created_at = datetime.now(UTC)
    gdpr.updated_at = datetime.now(UTC)
    gdpr.created_by = "admin"
    gdpr.updated_by = "admin"
    gdpr.to_dict = MagicMock(
        return_value={
            "is_verified": True,
            "is_available": True,
            "digital_signature": None,
            "notes": None,
            "created_at": gdpr.created_at,
            "updated_at": gdpr.updated_at,
            "created_by": "admin",
            "updated_by": "admin",
        }
    )
    return gdpr


@pytest.fixture
def mock_db_session():
    """Crée une session de base de données mock."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_fhir_client(mock_fhir_practitioner):
    """Crée un client FHIR mock."""
    client = AsyncMock()
    client.read = AsyncMock(return_value=mock_fhir_practitioner)
    client.update = AsyncMock(return_value=mock_fhir_practitioner)
    return client


# =============================================================================
# Tests for helper functions
# =============================================================================


class TestExtractEmailFromFhir:
    """Tests pour _extract_email_from_fhir()."""

    def test_extract_email_success(self, mock_fhir_practitioner):
        """Doit extraire l'email correctement."""
        result = _extract_email_from_fhir(mock_fhir_practitioner)
        assert result == "amadou@hospital.sn"

    def test_extract_email_no_telecom(self):
        """Doit retourner None si pas de telecom."""
        practitioner = FHIRPractitioner(id="no-telecom", telecom=None)
        result = _extract_email_from_fhir(practitioner)
        assert result is None

    def test_extract_email_no_email_in_telecom(self):
        """Doit retourner None si pas d'email dans telecom."""
        practitioner = FHIRPractitioner(
            id="no-email",
            telecom=[ContactPoint(system="phone", value="+221771234567")],
        )
        result = _extract_email_from_fhir(practitioner)
        assert result is None

    def test_extract_email_multiple_telecom(self):
        """Doit extraire le premier email si plusieurs telecom."""
        practitioner = FHIRPractitioner(
            id="multi-telecom",
            telecom=[
                ContactPoint(system="phone", value="+221771234567"),
                ContactPoint(system="email", value="first@example.com"),
                ContactPoint(system="email", value="second@example.com"),
            ],
        )
        result = _extract_email_from_fhir(practitioner)
        assert result == "first@example.com"


class TestExtractKeycloakIdFromFhir:
    """Tests pour _extract_keycloak_id_from_fhir()."""

    def test_extract_keycloak_id_success(self, mock_fhir_practitioner):
        """Doit extraire le keycloak_user_id correctement."""
        result = _extract_keycloak_id_from_fhir(mock_fhir_practitioner)
        assert result == "keycloak-user-123"

    def test_extract_keycloak_id_no_identifier(self):
        """Doit retourner None si pas d'identifiers."""
        practitioner = FHIRPractitioner(id="no-identifier", identifier=None)
        result = _extract_keycloak_id_from_fhir(practitioner)
        assert result is None

    def test_extract_keycloak_id_wrong_system(self):
        """Doit retourner None si système non Keycloak."""
        practitioner = FHIRPractitioner(
            id="wrong-system",
            identifier=[Identifier(system="http://other.system", value="other-id")],
        )
        result = _extract_keycloak_id_from_fhir(practitioner)
        assert result is None

    def test_extract_keycloak_id_multiple_identifiers(self):
        """Doit trouver keycloak_id parmi plusieurs identifiers."""
        practitioner = FHIRPractitioner(
            id="multi-id",
            identifier=[
                Identifier(system="http://other.system", value="other-id"),
                Identifier(system=KEYCLOAK_SYSTEM, value="keycloak-found"),
                Identifier(system="http://another.system", value="another-id"),
            ],
        )
        result = _extract_keycloak_id_from_fhir(practitioner)
        assert result == "keycloak-found"


# =============================================================================
# Tests for mark_professional_under_investigation
# =============================================================================


class TestMarkProfessionalUnderInvestigation:
    """Tests pour mark_professional_under_investigation()."""

    @pytest.mark.asyncio
    async def test_mark_investigation_success(
        self, mock_db_session, mock_gdpr_metadata, mock_fhir_client
    ):
        """Doit marquer un professionnel sous enquête."""
        mock_db_session.get = AsyncMock(return_value=mock_gdpr_metadata)
        context = ProfessionalDeletionContext(reason="Fraude médicale suspectée")

        with (
            patch(
                "app.api.v1.endpoints.admin_professionals.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.api.v1.endpoints.admin_professionals.publish",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            result = await mark_professional_under_investigation(
                professional_id=1,
                context=context,
                db=mock_db_session,
            )

            # Vérifier les mises à jour GDPR
            assert mock_gdpr_metadata.under_investigation is True
            assert mock_gdpr_metadata.investigation_notes == "Fraude médicale suspectée"

            # Vérifier commit
            mock_db_session.commit.assert_called_once()
            mock_db_session.refresh.assert_called_once()

            # Vérifier publication événement
            mock_publish.assert_called_once()
            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.professional.investigation_started"

            # Vérifier résultat
            assert result is not None

    @pytest.mark.asyncio
    async def test_mark_investigation_default_notes(
        self, mock_db_session, mock_gdpr_metadata, mock_fhir_client
    ):
        """Doit utiliser notes par défaut si non fournies."""
        mock_db_session.get = AsyncMock(return_value=mock_gdpr_metadata)
        context = ProfessionalDeletionContext(reason=None)

        with (
            patch(
                "app.api.v1.endpoints.admin_professionals.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.api.v1.endpoints.admin_professionals.publish",
                new_callable=AsyncMock,
            ),
        ):
            await mark_professional_under_investigation(
                professional_id=1,
                context=context,
                db=mock_db_session,
            )

            assert mock_gdpr_metadata.investigation_notes == "Enquête médico-légale en cours"

    @pytest.mark.asyncio
    async def test_mark_investigation_not_found(self, mock_db_session):
        """Doit lever 404 si professionnel non trouvé."""
        mock_db_session.get = AsyncMock(return_value=None)
        context = ProfessionalDeletionContext(reason="Test")

        with pytest.raises(HTTPException) as exc_info:
            await mark_professional_under_investigation(
                professional_id=999,
                context=context,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404
        assert "999" in str(exc_info.value.detail)


# =============================================================================
# Tests for remove_investigation_status
# =============================================================================


class TestRemoveInvestigationStatus:
    """Tests pour remove_investigation_status()."""

    @pytest.mark.asyncio
    async def test_remove_investigation_success(
        self, mock_db_session, mock_gdpr_metadata, mock_fhir_client
    ):
        """Doit retirer le statut d'enquête."""
        mock_gdpr_metadata.under_investigation = True
        mock_gdpr_metadata.investigation_notes = "Notes précédentes"
        mock_db_session.get = AsyncMock(return_value=mock_gdpr_metadata)

        with (
            patch(
                "app.api.v1.endpoints.admin_professionals.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.api.v1.endpoints.admin_professionals.publish",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            result = await remove_investigation_status(
                professional_id=1,
                db=mock_db_session,
            )

            # Vérifier les mises à jour GDPR
            assert mock_gdpr_metadata.under_investigation is False
            assert mock_gdpr_metadata.investigation_notes is None

            # Vérifier commit
            mock_db_session.commit.assert_called_once()

            # Vérifier publication événement
            mock_publish.assert_called_once()
            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.professional.investigation_cleared"

            assert result is not None

    @pytest.mark.asyncio
    async def test_remove_investigation_not_found(self, mock_db_session):
        """Doit lever 404 si professionnel non trouvé."""
        mock_db_session.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await remove_investigation_status(
                professional_id=999,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404


# =============================================================================
# Tests for restore_soft_deleted_professional
# =============================================================================


class TestRestoreSoftDeletedProfessional:
    """Tests pour restore_soft_deleted_professional()."""

    @pytest.mark.asyncio
    async def test_restore_success(
        self, mock_db_session, mock_gdpr_metadata, mock_fhir_client, mock_fhir_practitioner
    ):
        """Doit restaurer un professionnel soft deleted."""
        mock_gdpr_metadata.soft_deleted_at = datetime.now(UTC) - timedelta(days=3)
        mock_gdpr_metadata.deletion_reason = "user_request"
        mock_gdpr_metadata.anonymized_at = None
        mock_db_session.get = AsyncMock(return_value=mock_gdpr_metadata)

        restore_request = ProfessionalRestoreRequest(restore_reason="Erreur administrative")

        with (
            patch(
                "app.api.v1.endpoints.admin_professionals.get_fhir_client",
                return_value=mock_fhir_client,
            ),
            patch(
                "app.api.v1.endpoints.admin_professionals.publish",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            result = await restore_soft_deleted_professional(
                professional_id=1,
                restore_request=restore_request,
                db=mock_db_session,
            )

            # Vérifier les mises à jour GDPR
            assert mock_gdpr_metadata.soft_deleted_at is None
            assert mock_gdpr_metadata.deletion_reason is None

            # Vérifier mise à jour FHIR
            assert mock_fhir_practitioner.active is True
            mock_fhir_client.update.assert_called_once()

            # Vérifier publication événement
            mock_publish.assert_called_once()
            call_args = mock_publish.call_args
            assert call_args[0][0] == "identity.professional.restored"
            assert call_args[0][1]["restore_reason"] == "Erreur administrative"

            assert result is not None

    @pytest.mark.asyncio
    async def test_restore_not_found(self, mock_db_session):
        """Doit lever 404 si professionnel non trouvé."""
        mock_db_session.get = AsyncMock(return_value=None)
        restore_request = ProfessionalRestoreRequest(restore_reason="Test")

        with pytest.raises(HTTPException) as exc_info:
            await restore_soft_deleted_professional(
                professional_id=999,
                restore_request=restore_request,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_restore_already_anonymized(self, mock_db_session, mock_gdpr_metadata):
        """Doit lever 422 si déjà anonymisé."""
        mock_gdpr_metadata.soft_deleted_at = datetime.now(UTC) - timedelta(days=10)
        mock_gdpr_metadata.anonymized_at = datetime.now(UTC) - timedelta(days=3)
        mock_db_session.get = AsyncMock(return_value=mock_gdpr_metadata)

        restore_request = ProfessionalRestoreRequest(restore_reason="Tentative")

        with pytest.raises(HTTPException) as exc_info:
            await restore_soft_deleted_professional(
                professional_id=1,
                restore_request=restore_request,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 422
        assert "already anonymized" in str(exc_info.value.detail)


# =============================================================================
# Tests for list_soft_deleted_professionals
# =============================================================================


class TestListSoftDeletedProfessionals:
    """Tests pour list_soft_deleted_professionals()."""

    @pytest.mark.asyncio
    async def test_list_deleted_success(
        self, mock_db_session, mock_gdpr_metadata, mock_fhir_client
    ):
        """Doit lister les professionnels soft deleted."""
        mock_gdpr_metadata.soft_deleted_at = datetime.now(UTC) - timedelta(days=3)
        mock_gdpr_metadata.deletion_reason = "user_request"

        # Créer un résultat de requête mock
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[mock_gdpr_metadata])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.api.v1.endpoints.admin_professionals.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await list_soft_deleted_professionals(db=mock_db_session)

            assert len(result) == 1
            assert result[0].professional_id == 1
            assert result[0].keycloak_user_id == "keycloak-user-123"
            assert result[0].email == "amadou@hospital.sn"
            assert result[0].deletion_reason == "user_request"

    @pytest.mark.asyncio
    async def test_list_deleted_empty(self, mock_db_session, mock_fhir_client):
        """Doit retourner liste vide si aucun soft deleted."""
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.api.v1.endpoints.admin_professionals.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await list_soft_deleted_professionals(db=mock_db_session)

            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_list_deleted_fhir_error_handled(self, mock_db_session, mock_gdpr_metadata):
        """Doit gérer les erreurs FHIR gracieusement."""
        mock_gdpr_metadata.soft_deleted_at = datetime.now(UTC) - timedelta(days=3)
        mock_gdpr_metadata.deletion_reason = "admin_termination"

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[mock_gdpr_metadata])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # FHIR client qui lève une exception
        failing_fhir_client = AsyncMock()
        failing_fhir_client.read = AsyncMock(side_effect=Exception("FHIR unavailable"))

        with patch(
            "app.api.v1.endpoints.admin_professionals.get_fhir_client",
            return_value=failing_fhir_client,
        ):
            result = await list_soft_deleted_professionals(db=mock_db_session)

            # Doit retourner la liste malgré l'erreur FHIR
            assert len(result) == 1
            assert result[0].professional_id == 1
            # Email sera le fallback car FHIR a échoué
            assert result[0].email == "[Email non disponible]"

    @pytest.mark.asyncio
    async def test_list_deleted_multiple_professionals(self, mock_db_session, mock_fhir_client):
        """Doit lister plusieurs professionnels soft deleted."""
        # Créer plusieurs GDPR metadata mocks
        gdpr1 = MagicMock(spec=ProfessionalGdprMetadata)
        gdpr1.id = 1
        gdpr1.fhir_resource_id = "fhir-1"
        gdpr1.keycloak_user_id = "keycloak-1"
        gdpr1.soft_deleted_at = datetime.now(UTC) - timedelta(days=2)
        gdpr1.anonymized_at = None
        gdpr1.deletion_reason = "user_request"

        gdpr2 = MagicMock(spec=ProfessionalGdprMetadata)
        gdpr2.id = 2
        gdpr2.fhir_resource_id = "fhir-2"
        gdpr2.keycloak_user_id = "keycloak-2"
        gdpr2.soft_deleted_at = datetime.now(UTC) - timedelta(days=5)
        gdpr2.anonymized_at = None
        gdpr2.deletion_reason = "admin_termination"

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all = MagicMock(return_value=[gdpr1, gdpr2])
        mock_result.scalars = MagicMock(return_value=mock_scalars)
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.api.v1.endpoints.admin_professionals.get_fhir_client",
            return_value=mock_fhir_client,
        ):
            result = await list_soft_deleted_professionals(db=mock_db_session)

            assert len(result) == 2
            assert result[0].professional_id == 1
            assert result[0].deletion_reason == "user_request"
            assert result[1].professional_id == 2
            assert result[1].deletion_reason == "admin_termination"
