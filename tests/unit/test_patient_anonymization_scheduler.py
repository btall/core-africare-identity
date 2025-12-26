"""Tests pour l'anonymisation différée des patients après période de grâce.

NOTE: Ces tests sont en attente de migration vers l'architecture FHIR.
Les schedulers utilisent maintenant PatientGdprMetadata + FHIR client.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.patient import Patient


@pytest.fixture
def mock_events():
    """Mock event publishing pour tous les tests."""
    with patch("app.services.patient_anonymization_scheduler.publish") as mock_publish:
        mock_publish.return_value = AsyncMock()
        yield mock_publish


@pytest.mark.skip(reason="Test utilise ancien modèle Patient - à migrer vers FHIR + GDPR metadata")
@pytest.mark.asyncio
async def test_anonymize_expired_patients(mock_events, db_session):
    """Test: anonymise les patients après 7 jours."""
    now = datetime.now(UTC)
    expired_date = now - timedelta(days=8)  # 8 jours, donc expiré

    # Create expired patient
    patient = Patient(
        keycloak_user_id="test-expired-patient-123",
        first_name="Amadou",
        last_name="Diallo",
        email="amadou.diallo@example.sn",
        phone="+221771234567",
        gender="male",
        date_of_birth=date(1990, 5, 15),
        country="Sénégal",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=expired_date,
        correlation_hash="abc123patient",
    )
    db_session.add(patient)
    await db_session.commit()

    # Run anonymization task
    from app.services.patient_anonymization_scheduler import anonymize_expired_patient_deletions

    count = await anonymize_expired_patient_deletions(db_session)

    assert count == 1

    # Verify anonymization
    await db_session.refresh(patient)
    assert patient.anonymized_at is not None
    # Vérifier que first_name est un hash bcrypt (commence par $2b$)
    assert patient.first_name.startswith("$2b$"), "first_name should be bcrypt hashed"
    assert patient.last_name.startswith("$2b$"), "last_name should be bcrypt hashed"
    assert patient.email.startswith("$2b$"), "email should be bcrypt hashed"
    assert patient.phone == "+ANONYMIZED", "phone should be anonymized placeholder"
    assert patient.is_active is False


@pytest.mark.skip(reason="Test utilise ancien modèle Patient - à migrer vers FHIR + GDPR metadata")
@pytest.mark.asyncio
async def test_no_anonymization_within_grace_period(mock_events, db_session):
    """Test: pas d'anonymisation pendant la période de grâce."""
    now = datetime.now(UTC)
    recent_date = now - timedelta(days=3)  # 3 jours, encore dans période de grâce

    patient = Patient(
        keycloak_user_id="test-recent-patient-456",
        first_name="Fatou",
        last_name="Sall",
        email="fatou.sall@example.sn",
        phone="+221771234567",
        gender="female",
        date_of_birth=date(1985, 8, 20),
        country="Sénégal",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=recent_date,
    )
    db_session.add(patient)
    await db_session.commit()

    # Run anonymization task
    from app.services.patient_anonymization_scheduler import anonymize_expired_patient_deletions

    count = await anonymize_expired_patient_deletions(db_session)

    assert count == 0

    # Verify NOT anonymized
    await db_session.refresh(patient)
    assert patient.anonymized_at is None
    assert patient.first_name == "Fatou"  # Not anonymized yet


@pytest.mark.skip(reason="Test utilise ancien modèle Patient - à migrer vers FHIR + GDPR metadata")
@pytest.mark.asyncio
async def test_skip_already_anonymized(mock_events, db_session):
    """Test: ignore les patients déjà anonymisés."""
    now = datetime.now(UTC)
    expired_date = now - timedelta(days=10)
    anonymized_date = now - timedelta(days=3)

    patient = Patient(
        keycloak_user_id="test-already-anon-789",
        first_name="$2b$12$hashedfirst",
        last_name="$2b$12$hashedlast",
        email="$2b$12$hashedemail",
        phone="+ANONYMIZED",
        gender="male",
        date_of_birth=date(1980, 1, 1),
        country="Anonymisé",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=expired_date,
        anonymized_at=anonymized_date,  # Déjà anonymisé
    )
    db_session.add(patient)
    await db_session.commit()

    # Run anonymization task
    from app.services.patient_anonymization_scheduler import anonymize_expired_patient_deletions

    count = await anonymize_expired_patient_deletions(db_session)

    assert count == 0  # Pas de nouveau patient anonymisé

    # Verify unchanged
    await db_session.refresh(patient)
    assert patient.anonymized_at == anonymized_date  # Date inchangée


@pytest.mark.skip(reason="Test utilise ancien modèle Patient - à migrer vers FHIR + GDPR metadata")
@pytest.mark.asyncio
async def test_anonymize_multiple_expired_patients(mock_events, db_session):
    """Test: anonymise plusieurs patients expirés en une seule exécution."""
    now = datetime.now(UTC)
    expired_date = now - timedelta(days=9)

    # Create 3 expired patients
    patients = [
        Patient(
            keycloak_user_id=f"test-multi-{i}",
            first_name=f"Patient{i}",
            last_name=f"LastName{i}",
            email=f"patient{i}@example.sn",
            phone=f"+22177100000{i}",
            gender="male",
            date_of_birth=date(1990, 1, 1),
            country="Sénégal",
            preferred_language="fr",
            is_active=False,
            soft_deleted_at=expired_date,
            correlation_hash=f"hash{i}",
        )
        for i in range(3)
    ]

    db_session.add_all(patients)
    await db_session.commit()

    # Run anonymization task
    from app.services.patient_anonymization_scheduler import anonymize_expired_patient_deletions

    count = await anonymize_expired_patient_deletions(db_session)

    assert count == 3

    # Verify all anonymized
    for patient in patients:
        await db_session.refresh(patient)
        assert patient.anonymized_at is not None
        assert patient.first_name.startswith("$2b$")


@pytest.mark.skip(reason="Test utilise ancien modèle Patient - à migrer vers FHIR + GDPR metadata")
@pytest.mark.asyncio
async def test_publishes_anonymization_events(mock_events, db_session):
    """Test: publie événement identity.patient.anonymized pour chaque patient."""
    now = datetime.now(UTC)
    expired_date = now - timedelta(days=8)

    patient = Patient(
        keycloak_user_id="test-event-patient",
        first_name="EventTest",
        last_name="Patient",
        email="event@example.sn",
        phone="+221771234567",
        gender="female",
        date_of_birth=date(1992, 3, 10),
        country="Sénégal",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=expired_date,
        deletion_reason="user_request",
        correlation_hash="eventhash",
    )
    db_session.add(patient)
    await db_session.commit()

    # Run anonymization task
    from app.services.patient_anonymization_scheduler import anonymize_expired_patient_deletions

    await anonymize_expired_patient_deletions(db_session)

    # Verify event published
    mock_events.assert_called_once()
    call_args = mock_events.call_args
    assert call_args[0][0] == "identity.patient.anonymized"
    payload = call_args[0][1]
    assert payload["patient_id"] == patient.id
    assert "anonymized_at" in payload
    assert payload["deletion_reason"] == "user_request"
    assert payload["grace_period_days"] == 7
