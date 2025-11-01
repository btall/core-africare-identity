"""Tests pour l'anonymisation différée après période de grâce."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.professional import Professional


@pytest.fixture
def mock_events():
    """Mock event publishing pour tous les tests."""
    with patch("app.services.anonymization_scheduler.publish") as mock_publish:
        mock_publish.return_value = AsyncMock()
        yield mock_publish


@pytest.mark.asyncio
async def test_anonymize_expired_professionals(mock_events, db_session):
    """Test: anonymise les professionnels après 7 jours."""
    now = datetime.now(UTC)
    expired_date = now - timedelta(days=8)  # 8 jours, donc expiré

    # Create expired professional
    professional = Professional(
        keycloak_user_id="test-expired-123",
        first_name="Dr",
        last_name="Sow",
        email="dr.sow@hospital.sn",
        phone="+221771234567",
        specialty="Médecine générale",
        professional_type="physician",
        title="Dr",
        is_active=False,
        soft_deleted_at=expired_date,
        correlation_hash="abc123",
    )
    db_session.add(professional)
    await db_session.commit()

    # Run anonymization task
    from app.services.anonymization_scheduler import anonymize_expired_deletions

    count = await anonymize_expired_deletions(db_session)

    assert count == 1

    # Verify anonymization
    await db_session.refresh(professional)
    assert professional.anonymized_at is not None
    # Vérifier que first_name est un hash bcrypt (commence par $2b$)
    assert professional.first_name.startswith("$2b$"), "first_name should be bcrypt hashed"
    assert professional.last_name.startswith("$2b$"), "last_name should be bcrypt hashed"
    assert professional.email.startswith("$2b$"), "email should be bcrypt hashed"
    assert professional.phone == "+ANONYMIZED", "phone should be anonymized placeholder"
    assert professional.is_active is False


@pytest.mark.asyncio
async def test_no_anonymization_within_grace_period(mock_events, db_session):
    """Test: pas d'anonymisation pendant la période de grâce."""
    now = datetime.now(UTC)
    recent_date = now - timedelta(days=3)  # 3 jours, encore dans période de grâce

    professional = Professional(
        keycloak_user_id="test-recent-123",
        first_name="Dr",
        last_name="Ba",
        email="dr.ba@hospital.sn",
        phone="+221771234567",
        specialty="Neurologie",
        professional_type="physician",
        title="Dr",
        is_active=False,
        soft_deleted_at=recent_date,
    )
    db_session.add(professional)
    await db_session.commit()

    # Run anonymization task
    from app.services.anonymization_scheduler import anonymize_expired_deletions

    count = await anonymize_expired_deletions(db_session)

    assert count == 0

    # Verify NOT anonymized
    await db_session.refresh(professional)
    assert professional.anonymized_at is None
    assert professional.first_name == "Dr"  # Not anonymized yet
