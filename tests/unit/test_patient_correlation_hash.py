"""Tests pour le système de corrélation hash des patients."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from app.models.patient import Patient
from app.services.keycloak_sync_service import (
    _check_returning_patient,
    _generate_patient_correlation_hash,
)


def test_generate_patient_correlation_hash():
    """Test: génération de hash SHA-256 déterministe pour patients."""
    email = "amadou@example.sn"
    national_id = "1234567890"

    # Generate hash
    hash1 = _generate_patient_correlation_hash(email, national_id)

    # Verify format (64 caractères hexadécimaux)
    assert len(hash1) == 64
    assert all(c in "0123456789abcdef" for c in hash1)

    # Verify deterministic (même entrée = même hash)
    hash2 = _generate_patient_correlation_hash(email, national_id)
    assert hash1 == hash2


def test_patient_correlation_hash_with_salt():
    """Test: hash inclut un salt pour sécurité."""
    email = "fatou@example.sn"
    national_id = "9876543210"

    # Hash devrait être différent d'un simple SHA-256(email+national_id)
    simple_hash = hashlib.sha256(f"{email}|{national_id}".encode()).hexdigest()
    correlation_hash = _generate_patient_correlation_hash(email, national_id)

    assert correlation_hash != simple_hash, "Hash should include salt"


def test_patient_correlation_hash_without_national_id():
    """Test: hash fonctionne sans national_id (optionnel)."""
    email = "moussa@example.sn"

    # Generate hash sans national_id
    hash1 = _generate_patient_correlation_hash(email, national_id=None)

    assert len(hash1) == 64

    # Devrait être déterministe
    hash2 = _generate_patient_correlation_hash(email, national_id=None)
    assert hash1 == hash2


def test_patient_correlation_hash_uniqueness():
    """Test: hash différent pour des patients différents."""
    hash1 = _generate_patient_correlation_hash("amadou@example.sn", "111")
    hash2 = _generate_patient_correlation_hash("fatou@example.sn", "222")
    hash3 = _generate_patient_correlation_hash(
        "amadou@example.sn", "222"
    )  # Même email, ID différent

    assert hash1 != hash2
    assert hash1 != hash3
    assert hash2 != hash3


@pytest.mark.asyncio
async def test_check_returning_patient_found(db_session):
    """Test: détecte un patient anonymisé revenant avec même email/national_id."""
    email = "returning@example.sn"
    national_id = "1234567890"
    correlation_hash = _generate_patient_correlation_hash(email, national_id)

    # Create anonymized patient
    old_patient = Patient(
        keycloak_user_id="old-user-123",
        first_name="$2b$12$hashed",
        last_name="$2b$12$hashed",
        email="$2b$12$hashed",
        phone="+ANONYMIZED",
        gender="male",
        date_of_birth="1990-01-01",
        country="Anonymisé",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=10),
        anonymized_at=datetime.now(UTC) - timedelta(days=3),
        correlation_hash=correlation_hash,
    )
    db_session.add(old_patient)
    await db_session.commit()

    # Check for returning patient
    returning = await _check_returning_patient(db_session, email, national_id)

    assert returning is not None
    assert returning.id == old_patient.id
    assert returning.correlation_hash == correlation_hash
    assert returning.anonymized_at is not None


@pytest.mark.asyncio
async def test_check_returning_patient_not_found(db_session):
    """Test: ne trouve pas de patient si nouveau (pas anonymisé avant)."""
    email = "new@example.sn"
    national_id = "9999999999"

    # Check for returning patient (should not find)
    returning = await _check_returning_patient(db_session, email, national_id)

    assert returning is None


@pytest.mark.asyncio
async def test_check_returning_patient_not_anonymized_yet(db_session):
    """Test: ignore les patients soft deleted mais pas encore anonymisés."""
    email = "softdeleted@example.sn"
    national_id = "5555555555"
    correlation_hash = _generate_patient_correlation_hash(email, national_id)

    # Create soft deleted patient (NOT anonymized yet)
    patient = Patient(
        keycloak_user_id="soft-user-456",
        first_name="Amadou",
        last_name="Diallo",
        email=email,
        phone="+221771234567",
        gender="male",
        date_of_birth="1990-01-01",
        country="Sénégal",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=3),
        anonymized_at=None,  # PAS ENCORE anonymisé
        correlation_hash=correlation_hash,
    )
    db_session.add(patient)
    await db_session.commit()

    # Check for returning patient (should NOT find because not anonymized)
    returning = await _check_returning_patient(db_session, email, national_id)

    assert returning is None


@pytest.mark.asyncio
async def test_check_returning_patient_without_national_id(db_session):
    """Test: détection fonctionne avec email seul (sans national_id)."""
    email = "email-only@example.sn"
    correlation_hash = _generate_patient_correlation_hash(email, national_id=None)

    # Create anonymized patient
    old_patient = Patient(
        keycloak_user_id="email-only-user",
        first_name="$2b$12$hashed",
        last_name="$2b$12$hashed",
        email="$2b$12$hashed",
        phone="+ANONYMIZED",
        gender="female",
        date_of_birth="1985-01-01",
        country="Anonymisé",
        preferred_language="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=10),
        anonymized_at=datetime.now(UTC) - timedelta(days=3),
        correlation_hash=correlation_hash,
    )
    db_session.add(old_patient)
    await db_session.commit()

    # Check for returning patient (sans national_id)
    returning = await _check_returning_patient(db_session, email, national_id=None)

    assert returning is not None
    assert returning.id == old_patient.id
