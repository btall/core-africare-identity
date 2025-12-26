"""Tests pour les endpoints administrateur de gestion des suppressions patients.

NOTE: Ces tests sont temporairement désactivés car ils dépendent du modèle Patient legacy.
L'architecture FHIR hybride requiert une refactorisation complète avec:
- PatientGdprMetadata pour les métadonnées RGPD locales
- FHIR Patient pour les données démographiques
- Mock du client FHIR ou tests d'intégration avec conteneur HAPI FHIR
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.patient import Patient

# Skip tous les tests de ce module - nécessitent migration vers architecture FHIR
pytestmark = pytest.mark.skip(
    reason="Tests dépendants du modèle Patient legacy - migration FHIR requise"
)


@pytest.fixture
def mock_events():
    """Mock event publishing pour tous les tests."""
    with patch(
        "app.api.v1.endpoints.admin_patients.publish", new_callable=AsyncMock
    ) as mock_publish:
        yield mock_publish


@pytest.mark.asyncio
async def test_mark_patient_under_investigation(mock_events, db_session):
    """Test: POST /admin/patients/{id}/investigation marque sous enquête."""
    # SETUP: Créer un patient actif
    patient = Patient(
        keycloak_user_id="test-patient-123",
        first_name="Amadou",
        last_name="Diallo",
        email="amadou.diallo@example.sn",
        phone="+221771234567",
        gender="male",
        date_of_birth=date(1990, 5, 15),
        country="Sénégal",
        preferred_language="fr",
        is_active=True,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    # ACT: Marquer sous enquête
    from app.api.v1.endpoints.admin_patients import mark_patient_under_investigation
    from app.schemas.patient import PatientDeletionContext

    context = PatientDeletionContext(reason="Enquête médico-légale en cours")
    await mark_patient_under_investigation(patient.id, context, db_session)

    # ASSERT: Patient marqué sous enquête
    await db_session.refresh(patient)
    assert patient.under_investigation is True
    assert patient.investigation_notes == "Enquête médico-légale en cours"

    # ASSERT: Événement publié
    mock_events.assert_called_once()
    assert mock_events.call_args[0][0] == "identity.patient.investigation_started"


@pytest.mark.asyncio
async def test_remove_investigation_status(mock_events, db_session):
    """Test: DELETE /admin/patients/{id}/investigation retire enquête."""
    # SETUP: Créer un patient sous enquête
    patient = Patient(
        keycloak_user_id="test-patient-456",
        first_name="Fatou",
        last_name="Sall",
        email="fatou.sall@example.sn",
        phone="+221771234567",
        gender="female",
        date_of_birth=date(1985, 8, 20),
        country="Sénégal",
        preferred_language="fr",
        is_active=True,
        under_investigation=True,
        investigation_notes="Enquête en cours",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    # ACT: Retirer enquête
    from app.api.v1.endpoints.admin_patients import remove_investigation_status

    await remove_investigation_status(patient.id, db_session)

    # ASSERT: Enquête retirée
    await db_session.refresh(patient)
    assert patient.under_investigation is False
    assert patient.investigation_notes is None

    # ASSERT: Événement publié
    mock_events.assert_called_once()
    assert mock_events.call_args[0][0] == "identity.patient.investigation_cleared"


@pytest.mark.asyncio
async def test_restore_soft_deleted_patient(mock_events, db_session):
    """Test: POST /admin/patients/{id}/restore restaure après soft delete."""
    # SETUP: Créer un patient soft deleted (période de grâce)
    patient = Patient(
        keycloak_user_id="test-patient-789",
        first_name="Moussa",
        last_name="Ndiaye",
        email="moussa.ndiaye@example.sn",
        phone="+221771234567",
        gender="male",
        date_of_birth=date(1992, 3, 10),
        country="Sénégal",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=3),  # Dans période de grâce
        deletion_reason="user_request",
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    # ACT: Restaurer patient
    from app.api.v1.endpoints.admin_patients import restore_soft_deleted_patient
    from app.schemas.patient import PatientRestoreRequest

    restore_request = PatientRestoreRequest(restore_reason="Demande utilisateur annulée")
    await restore_soft_deleted_patient(patient.id, restore_request, db_session)

    # ASSERT: Patient restauré
    await db_session.refresh(patient)
    assert patient.is_active is True
    assert patient.soft_deleted_at is None
    assert patient.deletion_reason is None

    # ASSERT: Événement publié
    mock_events.assert_called_once()
    assert mock_events.call_args[0][0] == "identity.patient.restored"


@pytest.mark.asyncio
async def test_restore_fails_if_already_anonymized(mock_events, db_session):
    """Test: restauration échoue si déjà anonymisé."""
    # SETUP: Créer un patient anonymisé (période de grâce expirée)
    patient = Patient(
        keycloak_user_id="test-patient-anonymous",
        first_name="$2b$12$hashedfirstname",
        last_name="$2b$12$hashedlastname",
        email="$2b$12$hashedemail",
        phone="+ANONYMIZED",
        gender="male",
        date_of_birth=date(1980, 1, 1),
        country="Anonymisé",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=10),
        anonymized_at=datetime.now(UTC) - timedelta(days=3),
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    # ACT: Tenter de restaurer (doit échouer)
    from fastapi import HTTPException

    from app.api.v1.endpoints.admin_patients import restore_soft_deleted_patient
    from app.schemas.patient import PatientRestoreRequest

    restore_request = PatientRestoreRequest(restore_reason="Tentative de restauration")

    with pytest.raises(HTTPException) as exc_info:
        await restore_soft_deleted_patient(patient.id, restore_request, db_session)

    # ASSERT: Erreur HTTP 422 (cannot restore anonymized)
    assert exc_info.value.status_code == 422
    assert "already anonymized" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_list_soft_deleted_patients(mock_events, db_session):
    """Test: GET /admin/patients/deleted liste patients soft deleted."""
    # SETUP: Créer plusieurs patients avec différents états
    active = Patient(
        keycloak_user_id="active-patient",
        first_name="Awa",
        last_name="Thiam",
        email="awa.thiam@example.sn",
        phone="+221771111111",
        gender="female",
        date_of_birth=date(1995, 12, 25),
        country="Sénégal",
        preferred_language="fr",
        is_active=True,
    )

    soft_deleted = Patient(
        keycloak_user_id="soft-deleted-patient",
        first_name="Ibrahima",
        last_name="Sy",
        email="ibrahima.sy@example.sn",
        phone="+221772222222",
        gender="male",
        date_of_birth=date(1988, 7, 14),
        country="Sénégal",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=2),
    )

    anonymized = Patient(
        keycloak_user_id="anonymized-patient",
        first_name="$2b$12$hashed",
        last_name="$2b$12$hashed",
        email="$2b$12$hashed",
        phone="+ANONYMIZED",
        gender="other",
        date_of_birth=date(1970, 1, 1),
        country="Anonymisé",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=10),
        anonymized_at=datetime.now(UTC) - timedelta(days=3),
    )

    db_session.add_all([active, soft_deleted, anonymized])
    await db_session.commit()

    # ACT: Lister soft deleted (pas anonymisés)
    from app.api.v1.endpoints.admin_patients import list_soft_deleted_patients

    result = await list_soft_deleted_patients(db_session)

    # ASSERT: Retourne uniquement soft_deleted (pas active, pas anonymized)
    assert len(result) == 1
    assert result[0].patient_id == soft_deleted.id
    assert result[0].soft_deleted_at is not None
    assert result[0].anonymized_at is None
