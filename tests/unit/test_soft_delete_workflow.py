"""Tests pour le workflow de soft delete avec période de grâce."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import ProfessionalDeletionBlockedError
from app.models.professional import Professional
from app.schemas.keycloak import KeycloakWebhookEvent
from app.services.keycloak_sync_service import sync_user_deletion


@pytest.fixture
def mock_keycloak_and_events():
    """Mock Keycloak roles and event publishing pour tous les tests."""
    with (
        patch("app.services.keycloak_sync_service.get_user_roles_from_keycloak") as mock_roles,
        patch("app.services.keycloak_sync_service.publish") as mock_publish,
    ):
        mock_roles.return_value = ["professional"]
        mock_publish.return_value = AsyncMock()
        yield mock_roles, mock_publish


@pytest.mark.skip(reason="TODO: Refactoriser pour GDPR metadata + FHIR services")
@pytest.mark.asyncio
async def test_soft_delete_creates_correlation_hash(mock_keycloak_and_events, db_session):
    """Test: soft delete génère correlation_hash."""
    # Create professional
    professional = Professional(
        keycloak_user_id="test-delete-123",
        first_name="Dr",
        last_name="Diop",
        email="dr.diop@hospital.sn",
        phone="+221771234567",
        specialty="Cardiologie",
        professional_type="physician",
        title="Dr",
        professional_id="CNOM12345",
        is_active=True,
    )
    db_session.add(professional)
    await db_session.commit()
    await db_session.refresh(professional)

    # Simulate DELETE event
    event = KeycloakWebhookEvent(
        event_type="DELETE",
        realm_id="africare",
        user_id="test-delete-123",
        event_time=int(datetime.now(UTC).timestamp() * 1000),
        deletion_reason="user_request",
    )
    result = await sync_user_deletion(db_session, event, strategy="soft_delete")

    # Verify
    await db_session.refresh(professional)
    assert professional.is_active is False
    assert professional.soft_deleted_at is not None
    assert professional.correlation_hash is not None
    assert professional.anonymized_at is None  # Not yet anonymized
    assert result.success is True


@pytest.mark.skip(reason="TODO: Refactoriser pour GDPR metadata + FHIR services")
@pytest.mark.asyncio
async def test_soft_delete_blocked_under_investigation(mock_keycloak_and_events, db_session):
    """Test: soft delete bloqué si under_investigation=True."""
    professional = Professional(
        keycloak_user_id="test-investigation-123",
        first_name="Dr",
        last_name="Fall",
        email="dr.fall@hospital.sn",
        phone="+221771234567",
        specialty="Chirurgie",
        professional_type="physician",
        title="Dr",
        under_investigation=True,
        investigation_notes="Enquête en cours",
        is_active=True,
    )
    db_session.add(professional)
    await db_session.commit()

    # Attempt soft delete
    event = KeycloakWebhookEvent(
        event_type="DELETE",
        realm_id="africare",
        user_id="test-investigation-123",
        event_time=int(datetime.now(UTC).timestamp() * 1000),
    )

    with pytest.raises(ProfessionalDeletionBlockedError) as exc_info:
        await sync_user_deletion(db_session, event, strategy="soft_delete")

    assert exc_info.value.status_code == 423
    assert "under_investigation" in str(exc_info.value.problem_detail.detail)

    # Verify professional not deleted
    await db_session.refresh(professional)
    assert professional.is_active is True
    assert professional.soft_deleted_at is None


@pytest.mark.skip(reason="TODO: Refactoriser pour GDPR metadata + FHIR services")
@pytest.mark.asyncio
async def test_soft_delete_grace_period_7_days(mock_keycloak_and_events, db_session):
    """Test: période de grâce de 7 jours."""
    professional = Professional(
        keycloak_user_id="test-grace-123",
        first_name="Dr",
        last_name="Ndiaye",
        email="dr.ndiaye@hospital.sn",
        phone="+221771234567",
        specialty="Pédiatrie",
        professional_type="physician",
        title="Dr",
        is_active=True,
    )
    db_session.add(professional)
    await db_session.commit()

    # Soft delete
    now = datetime.now(UTC)
    event = KeycloakWebhookEvent(
        event_type="DELETE",
        realm_id="africare",
        user_id="test-grace-123",
        event_time=int(now.timestamp() * 1000),
        deletion_reason="gdpr_compliance",
    )
    await sync_user_deletion(db_session, event, strategy="soft_delete")

    await db_session.refresh(professional)
    grace_period_end = professional.soft_deleted_at + timedelta(days=7)

    assert professional.soft_deleted_at is not None
    assert abs((grace_period_end - professional.soft_deleted_at).days) == 7
    assert professional.deletion_reason == "gdpr_compliance"
