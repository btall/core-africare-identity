"""Tests pour la détection des retours de professionnels après anonymisation.

Ces tests utilisent le vrai client FHIR (HAPI FHIR sur port 8081).
Seuls Keycloak et les événements Redis sont mockés.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.models.gdpr_metadata import ProfessionalGdprMetadata
from app.schemas.keycloak import KeycloakUser, KeycloakWebhookEvent
from app.services.keycloak_sync_service import sync_user_registration


@pytest.fixture
def mock_keycloak_and_events():
    """Mock Keycloak roles et event publishing."""
    with (
        patch("app.services.keycloak_sync_service.get_user_roles_from_keycloak") as mock_roles,
        patch("app.services.keycloak_sync_service.publish") as mock_publish_sync,
        patch("app.services.professional_service.publish") as mock_publish_prof,
    ):
        mock_roles.return_value = ["professional"]
        # Mock publish pour keycloak_sync_service et professional_service
        mock_publish_sync.return_value = None
        mock_publish_prof.return_value = None
        yield mock_roles, mock_publish_sync


@pytest.mark.integration
@pytest.mark.asyncio
async def test_detect_returning_professional_after_anonymization(
    mock_keycloak_and_events, db_session, fhir_client
):
    """Test: détecte un professionnel qui revient après anonymisation via GDPR metadata."""
    # SETUP: Créer des métadonnées GDPR d'un professionnel anonymisé avec correlation_hash
    from app.services.keycloak_sync_service import _generate_correlation_hash

    original_email = "dr.diallo@hospital.sn"
    original_professional_id = None
    correlation_hash = _generate_correlation_hash(original_email, original_professional_id)

    old_gdpr_metadata = ProfessionalGdprMetadata(
        fhir_resource_id="fhir-old-practitioner",
        keycloak_user_id="old-user-123",
        is_verified=False,
        is_available=False,
        soft_deleted_at=datetime.now(UTC),
        anonymized_at=datetime.now(UTC),
        # Hash généré depuis email original + professional_id
        correlation_hash=correlation_hash,
    )
    db_session.add(old_gdpr_metadata)
    await db_session.commit()
    await db_session.refresh(old_gdpr_metadata)

    # ACT: Nouveau professionnel s'enregistre avec même email et professional_id
    event = KeycloakWebhookEvent(
        event_type="REGISTER",
        realm_id="africare",
        user_id="new-user-456",
        event_time=int(datetime.now(UTC).timestamp() * 1000),
        user=KeycloakUser(
            id="new-user-456",
            username="dr.diallo",
            email=original_email,  # Même email que le professionnel anonymisé
            first_name="Dr. Amadou",
            last_name="Diallo",
        ),
    )

    result = await sync_user_registration(db_session, event)

    # ASSERT: Professionnel créé avec succès
    assert result.success is True
    assert result.patient_id is not None  # ID du nouveau professionnel

    # ASSERT: Événement identity.professional.returning_user publié
    mock_publish = mock_keycloak_and_events[1]
    returning_user_calls = [
        call
        for call in mock_publish.call_args_list
        if call[0][0] == "identity.professional.returning_user"
    ]
    assert len(returning_user_calls) >= 1, "Événement returning_user doit être publié"

    # Vérifier les détails de l'événement
    returning_event = returning_user_calls[0][0][1]
    assert returning_event["new_keycloak_user_id"] == "new-user-456"
    assert returning_event["old_professional_id"] == old_gdpr_metadata.id
    assert returning_event["correlation_hash"] == old_gdpr_metadata.correlation_hash


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_detection_if_no_previous_anonymization(
    mock_keycloak_and_events, db_session, fhir_client
):
    """Test: pas de détection si aucun professionnel anonymisé avec ce hash."""
    # ACT: Nouveau professionnel s'enregistre (premier enregistrement)
    event = KeycloakWebhookEvent(
        event_type="REGISTER",
        realm_id="africare",
        user_id="new-user-789",
        event_time=int(datetime.now(UTC).timestamp() * 1000),
        user=KeycloakUser(
            id="new-user-789",
            username="dr.ndiaye",
            email="dr.ndiaye@clinic.sn",
            first_name="Dr. Fatou",
            last_name="Ndiaye",
        ),
    )

    result = await sync_user_registration(db_session, event)

    # ASSERT: Professionnel créé avec succès
    assert result.success is True
    assert result.patient_id is not None

    # ASSERT: Aucun événement returning_user publié
    mock_publish = mock_keycloak_and_events[1]
    returning_user_calls = [
        call
        for call in mock_publish.call_args_list
        if call[0][0] == "identity.professional.returning_user"
    ]
    assert len(returning_user_calls) == 0, "Pas d'événement returning_user si première inscription"


@pytest.mark.skip(reason="TODO: Nécessite extraction professional_id depuis Keycloak attributes")
@pytest.mark.integration
@pytest.mark.asyncio
async def test_detect_returning_professional_with_professional_id(
    mock_keycloak_and_events, db_session, fhir_client
):
    """Test: détection avec professional_id (CNOM) présent."""
    # SETUP: Métadonnées GDPR avec correlation_hash basé sur email+professional_id
    from app.services.keycloak_sync_service import _generate_correlation_hash

    original_email = "dr.sow@hospital.sn"
    original_professional_id = "CNOM12345"
    correlation_hash = _generate_correlation_hash(original_email, original_professional_id)

    old_gdpr_metadata = ProfessionalGdprMetadata(
        fhir_resource_id="fhir-old-practitioner-cnom",
        keycloak_user_id="old-user-cnom",
        is_verified=False,
        is_available=False,
        soft_deleted_at=datetime.now(UTC),
        anonymized_at=datetime.now(UTC),
        correlation_hash=correlation_hash,
    )
    db_session.add(old_gdpr_metadata)
    await db_session.commit()

    # ACT: Nouveau professionnel avec même email ET professional_id
    event = KeycloakWebhookEvent(
        event_type="REGISTER",
        realm_id="africare",
        user_id="new-user-cnom",
        event_time=int(datetime.now(UTC).timestamp() * 1000),
        user=KeycloakUser(
            id="new-user-cnom",
            username="dr.sow",
            email=original_email,
            first_name="Dr. Ibrahima",
            last_name="Sow",
        ),
    )

    result = await sync_user_registration(db_session, event)

    # ASSERT: Professionnel créé
    assert result.success is True

    # ASSERT: Événement returning_user publié
    mock_publish = mock_keycloak_and_events[1]
    returning_user_calls = [
        call
        for call in mock_publish.call_args_list
        if call[0][0] == "identity.professional.returning_user"
    ]
    assert len(returning_user_calls) >= 1
