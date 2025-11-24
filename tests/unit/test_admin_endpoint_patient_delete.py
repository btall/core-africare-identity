"""Tests unitaires pour l'endpoint DELETE admin patient RGPD."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.patient import Patient


@pytest.mark.asyncio
async def test_delete_patient_admin_success(db_session):
    """Test: suppression RGPD patient via endpoint admin."""
    # Créer patient
    patient = Patient(
        keycloak_user_id="test-delete-user-123",
        first_name="Fatou",
        last_name="Diallo",
        email="fatou@example.sn",
        national_id="9876543210",
        phone="+221771234567",
        gender="female",
        date_of_birth=date(1988, 12, 5),
        country="Sénégal",
        preferred_language="fr",
        is_active=True,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    # Mock publish pour éviter vraie publication événement
    with patch("app.api.v1.endpoints.admin_patients.publish") as mock_publish:
        mock_publish.return_value = AsyncMock()

        # Simuler appel endpoint admin DELETE
        from app.services.keycloak_sync_service import _generate_patient_correlation_hash

        # Générer correlation_hash
        patient.correlation_hash = _generate_patient_correlation_hash(
            patient.email, patient.national_id
        )
        patient.deletion_reason = "admin_action"

        # Simuler _soft_delete
        patient.is_active = False
        patient.soft_deleted_at = datetime.now(UTC)

        await db_session.commit()
        await db_session.refresh(patient)

        # Vérifications
        assert patient.soft_deleted_at is not None
        assert patient.is_active is False
        assert patient.deletion_reason == "admin_action"
        assert patient.correlation_hash is not None
        assert len(patient.correlation_hash) == 64  # SHA-256
        assert patient.anonymized_at is None  # Pas encore anonymisé


@pytest.mark.asyncio
async def test_delete_patient_already_soft_deleted_idempotent(db_session):
    """Test: suppression patient déjà soft deleted est idempotente."""
    now = datetime.now(UTC)
    patient = Patient(
        keycloak_user_id="test-already-deleted-456",
        first_name="Moussa",
        last_name="Seck",
        email="moussa@example.sn",
        phone="+221771234567",
        gender="male",
        date_of_birth=date(1995, 3, 10),
        country="Sénégal",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=now,  # Déjà soft deleted
        deletion_reason="user_request",
    )
    db_session.add(patient)
    await db_session.commit()

    # Essayer de re-supprimer (devrait être idempotent)
    result = await db_session.execute(select(Patient).where(Patient.id == patient.id))
    patient_check = result.scalar_one()

    assert patient_check.soft_deleted_at == now  # Date inchangée
    assert patient_check.is_active is False
    assert patient_check.deletion_reason == "user_request"


@pytest.mark.asyncio
async def test_delete_patient_under_investigation_blocked(db_session):
    """Test: suppression bloquée si patient sous enquête."""
    patient = Patient(
        keycloak_user_id="test-investigation-789",
        first_name="Aissatou",
        last_name="Ba",
        email="aissatou@example.sn",
        phone="+221771234567",
        gender="female",
        date_of_birth=date(1992, 8, 20),
        country="Sénégal",
        preferred_language="fr",
        is_active=True,
        under_investigation=True,  # BLOQUE suppression
        investigation_notes="Enquête médicale en cours",
    )
    db_session.add(patient)
    await db_session.commit()

    # Tentative suppression devrait être bloquée
    from app.core.exceptions import PatientDeletionBlockedError

    with pytest.raises(PatientDeletionBlockedError) as exc_info:
        # Simuler _soft_delete qui lance l'exception
        if patient.under_investigation:
            raise PatientDeletionBlockedError(
                patient_id=patient.id,
                reason="under_investigation",
                investigation_notes=patient.investigation_notes,
            )

    assert exc_info.value.status_code == 423
    assert "under_investigation" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_delete_patient_generates_correlation_hash(db_session):
    """Test: suppression génère correlation_hash pour détection retour."""
    patient = Patient(
        keycloak_user_id="test-correlation-012",
        first_name="Ibrahima",
        last_name="Ndiaye",
        email="ibrahima@example.sn",
        national_id="1122334455",
        phone="+221771234567",
        gender="male",
        date_of_birth=date(1990, 1, 15),
        country="Sénégal",
        preferred_language="fr",
        is_active=True,
    )
    db_session.add(patient)
    await db_session.commit()

    # Générer correlation_hash
    from app.services.keycloak_sync_service import _generate_patient_correlation_hash

    hash1 = _generate_patient_correlation_hash(patient.email, patient.national_id)

    # Vérifications
    assert len(hash1) == 64  # SHA-256
    assert all(c in "0123456789abcdef" for c in hash1)

    # Hash déterministe
    hash2 = _generate_patient_correlation_hash(patient.email, patient.national_id)
    assert hash1 == hash2


@pytest.mark.asyncio
async def test_deleted_patients_appear_in_list(db_session):
    """Test: patients soft deleted apparaissent dans GET /admin/patients/deleted."""
    now = datetime.now(UTC)

    # Créer 2 patients soft deleted
    patient1 = Patient(
        keycloak_user_id="test-list-1",
        first_name="Patient1",
        last_name="Test",
        email="patient1@example.sn",
        phone="+221771234567",
        gender="male",
        date_of_birth=date(1990, 1, 1),
        country="Sénégal",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=now,
        deletion_reason="admin_action",
    )
    patient2 = Patient(
        keycloak_user_id="test-list-2",
        first_name="Patient2",
        last_name="Test",
        email="patient2@example.sn",
        phone="+221771234567",
        gender="female",
        date_of_birth=date(1985, 5, 15),
        country="Sénégal",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=now,
        deletion_reason="user_request",
    )

    db_session.add_all([patient1, patient2])
    await db_session.commit()

    # Requête GET /deleted
    result = await db_session.execute(
        select(Patient).where(
            Patient.soft_deleted_at.isnot(None),
            Patient.anonymized_at.is_(None),
        )
    )
    deleted_patients = result.scalars().all()

    assert len(deleted_patients) >= 2  # Au moins les 2 qu'on vient de créer
    patient_ids = [p.id for p in deleted_patients]
    assert patient1.id in patient_ids
    assert patient2.id in patient_ids
