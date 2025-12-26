"""Tests unitaires pour les fonctions de corrélation hash."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gdpr_metadata import ProfessionalGdprMetadata
from app.services.keycloak_sync_service import (
    _check_returning_professional,
    _generate_correlation_hash,
)


def test_generate_correlation_hash_deterministic():
    """Test: Le hash est déterministe (mêmes inputs = même hash)."""
    email = "dr.diop@hospital.sn"
    professional_id = "CNOM12345"

    hash1 = _generate_correlation_hash(email, professional_id)
    hash2 = _generate_correlation_hash(email, professional_id)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex = 64 caractères


def test_generate_correlation_hash_different_inputs():
    """Test: Inputs différents produisent des hashs différents."""
    hash1 = _generate_correlation_hash("dr.diop@hospital.sn", "CNOM12345")
    hash2 = _generate_correlation_hash("dr.fall@hospital.sn", "CNOM12345")
    hash3 = _generate_correlation_hash("dr.diop@hospital.sn", "CNOM67890")

    assert hash1 != hash2
    assert hash1 != hash3
    assert hash2 != hash3


def test_generate_correlation_hash_none_professional_id():
    """Test: Gère professional_id=None sans erreur."""
    hash1 = _generate_correlation_hash("dr.diop@hospital.sn", None)
    hash2 = _generate_correlation_hash("dr.diop@hospital.sn", "")

    assert len(hash1) == 64
    # None et "" doivent produire le même hash (normalisé à "")
    assert hash1 == hash2


@pytest.mark.asyncio
async def test_check_returning_professional_not_found(db_session: AsyncSession):
    """Test: Retourne None si aucun professionnel anonymisé correspondant."""
    result = await _check_returning_professional(
        db_session, "new.professional@hospital.sn", "CNOM99999"
    )

    assert result is None


@pytest.mark.asyncio
async def test_check_returning_professional_found(db_session: AsyncSession):
    """Test: Détecte un professionnel anonymisé qui revient via GDPR metadata."""
    from datetime import UTC, datetime

    # Créer les métadonnées GDPR d'un professionnel anonymisé avec correlation_hash
    original_email = "dr.returning@hospital.sn"
    original_professional_id = "CNOM12345"
    correlation_hash = _generate_correlation_hash(original_email, original_professional_id)

    gdpr_metadata = ProfessionalGdprMetadata(
        fhir_resource_id="fhir-resource-id-anonymized",
        keycloak_user_id="test-old-keycloak-id",
        correlation_hash=correlation_hash,
        anonymized_at=datetime.now(UTC),
        is_verified=False,
        is_available=False,
    )
    db_session.add(gdpr_metadata)
    await db_session.commit()
    await db_session.refresh(gdpr_metadata)

    # Vérifier que la détection fonctionne
    result = await _check_returning_professional(
        db_session, original_email, original_professional_id
    )

    assert result is not None
    assert result.id == gdpr_metadata.id
    assert result.correlation_hash == correlation_hash
    assert result.anonymized_at is not None


@pytest.mark.asyncio
async def test_check_returning_professional_ignores_non_anonymized(db_session: AsyncSession):
    """Test: Ignore les professionnels actifs (non anonymisés) même avec hash correspondant."""
    email = "dr.active@hospital.sn"
    professional_id = "CNOM55555"
    correlation_hash = _generate_correlation_hash(email, professional_id)

    # Créer métadonnées GDPR d'un professionnel actif (non anonymisé)
    gdpr_metadata = ProfessionalGdprMetadata(
        fhir_resource_id="fhir-resource-id-active",
        keycloak_user_id="test-active-keycloak-id",
        correlation_hash=correlation_hash,
        anonymized_at=None,  # Pas anonymisé
        is_verified=True,
        is_available=True,
    )
    db_session.add(gdpr_metadata)
    await db_session.commit()

    # Ne doit PAS détecter comme "revenant" (non anonymisé)
    result = await _check_returning_professional(db_session, email, professional_id)

    assert result is None
