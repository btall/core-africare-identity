"""Tests pour les endpoints administrateur de gestion des suppressions."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.professional import Professional


@pytest.fixture
def mock_events():
    """Mock event publishing pour tous les tests."""
    with patch(
        "app.api.v1.endpoints.admin_professionals.publish", new_callable=AsyncMock
    ) as mock_publish:
        yield mock_publish


@pytest.mark.asyncio
async def test_mark_professional_under_investigation(mock_events, db_session):
    """Test: POST /admin/professionals/{id}/investigation marque sous enquête."""
    # SETUP: Créer un professionnel actif
    professional = Professional(
        keycloak_user_id="test-user-123",
        first_name="Dr",
        last_name="Diop",
        email="dr.diop@hospital.sn",
        phone="+221771234567",
        specialty="Cardiologie",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=True,
    )
    db_session.add(professional)
    await db_session.commit()
    await db_session.refresh(professional)

    # ACT: Marquer sous enquête
    from app.api.v1.endpoints.admin_professionals import mark_professional_under_investigation
    from app.schemas.professional import ProfessionalDeletionContext

    context = ProfessionalDeletionContext(reason="Enquête médico-légale en cours")
    await mark_professional_under_investigation(professional.id, context, db_session)

    # ASSERT: Professionnel marqué sous enquête
    await db_session.refresh(professional)
    assert professional.under_investigation is True
    assert professional.investigation_notes == "Enquête médico-légale en cours"

    # ASSERT: Événement publié
    mock_events.assert_called_once()
    assert mock_events.call_args[0][0] == "identity.professional.investigation_started"


@pytest.mark.asyncio
async def test_remove_investigation_status(mock_events, db_session):
    """Test: DELETE /admin/professionals/{id}/investigation retire enquête."""
    # SETUP: Créer un professionnel sous enquête
    professional = Professional(
        keycloak_user_id="test-user-456",
        first_name="Dr",
        last_name="Fall",
        email="dr.fall@hospital.sn",
        phone="+221771234567",
        specialty="Chirurgie",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=True,
        under_investigation=True,
        investigation_notes="Enquête en cours",
    )
    db_session.add(professional)
    await db_session.commit()
    await db_session.refresh(professional)

    # ACT: Retirer enquête
    from app.api.v1.endpoints.admin_professionals import remove_investigation_status

    await remove_investigation_status(professional.id, db_session)

    # ASSERT: Enquête retirée
    await db_session.refresh(professional)
    assert professional.under_investigation is False
    assert professional.investigation_notes is None

    # ASSERT: Événement publié
    mock_events.assert_called_once()
    assert mock_events.call_args[0][0] == "identity.professional.investigation_cleared"


@pytest.mark.asyncio
async def test_restore_soft_deleted_professional(mock_events, db_session):
    """Test: POST /admin/professionals/{id}/restore restaure après soft delete."""
    # SETUP: Créer un professionnel soft deleted (période de grâce)
    professional = Professional(
        keycloak_user_id="test-user-789",
        first_name="Dr",
        last_name="Ndiaye",
        email="dr.ndiaye@hospital.sn",
        phone="+221771234567",
        specialty="Pédiatrie",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=3),  # Dans période de grâce
        deletion_reason="user_request",
    )
    db_session.add(professional)
    await db_session.commit()
    await db_session.refresh(professional)

    # ACT: Restaurer professionnel
    from app.api.v1.endpoints.admin_professionals import restore_soft_deleted_professional
    from app.schemas.professional import ProfessionalRestoreRequest

    restore_request = ProfessionalRestoreRequest(restore_reason="Demande utilisateur annulée")
    await restore_soft_deleted_professional(professional.id, restore_request, db_session)

    # ASSERT: Professionnel restauré
    await db_session.refresh(professional)
    assert professional.is_active is True
    assert professional.soft_deleted_at is None
    assert professional.deletion_reason is None

    # ASSERT: Événement publié
    mock_events.assert_called_once()
    assert mock_events.call_args[0][0] == "identity.professional.restored"


@pytest.mark.asyncio
async def test_restore_fails_if_already_anonymized(mock_events, db_session):
    """Test: restauration échoue si déjà anonymisé."""
    # SETUP: Créer un professionnel anonymisé (période de grâce expirée)
    professional = Professional(
        keycloak_user_id="test-user-anonymous",
        first_name="$2b$12$hashedfirstname",
        last_name="$2b$12$hashedlastname",
        email="$2b$12$hashedemail",
        phone="+ANONYMIZED",
        specialty="Médecine générale",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=10),
        anonymized_at=datetime.now(UTC) - timedelta(days=3),
    )
    db_session.add(professional)
    await db_session.commit()
    await db_session.refresh(professional)

    # ACT: Tenter de restaurer (doit échouer)
    from fastapi import HTTPException

    from app.api.v1.endpoints.admin_professionals import restore_soft_deleted_professional
    from app.schemas.professional import ProfessionalRestoreRequest

    restore_request = ProfessionalRestoreRequest(restore_reason="Tentative de restauration")

    with pytest.raises(HTTPException) as exc_info:
        await restore_soft_deleted_professional(professional.id, restore_request, db_session)

    # ASSERT: Erreur HTTP 422 (cannot restore anonymized)
    assert exc_info.value.status_code == 422
    assert "already anonymized" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_list_soft_deleted_professionals(mock_events, db_session):
    """Test: GET /admin/professionals/deleted liste professionnels soft deleted."""
    # SETUP: Créer plusieurs professionnels avec différents états
    active = Professional(
        keycloak_user_id="active-user",
        first_name="Dr",
        last_name="Active",
        email="active@hospital.sn",
        phone="+221771111111",
        specialty="Cardiologie",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=True,
    )

    soft_deleted = Professional(
        keycloak_user_id="soft-deleted-user",
        first_name="Dr",
        last_name="SoftDeleted",
        email="softdeleted@hospital.sn",
        phone="+221772222222",
        specialty="Neurologie",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=2),
    )

    anonymized = Professional(
        keycloak_user_id="anonymized-user",
        first_name="$2b$12$hashed",
        last_name="$2b$12$hashed",
        email="$2b$12$hashed",
        phone="+ANONYMIZED",
        specialty="Pédiatrie",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=10),
        anonymized_at=datetime.now(UTC) - timedelta(days=3),
    )

    db_session.add_all([active, soft_deleted, anonymized])
    await db_session.commit()

    # ACT: Lister soft deleted (pas anonymisés)
    from app.api.v1.endpoints.admin_professionals import list_soft_deleted_professionals

    result = await list_soft_deleted_professionals(db_session)

    # ASSERT: Retourne uniquement soft_deleted (pas active, pas anonymized)
    assert len(result) == 1
    assert result[0].professional_id == soft_deleted.id
    assert result[0].soft_deleted_at is not None
    assert result[0].anonymized_at is None
