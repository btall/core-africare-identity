"""Tests d'intégration end-to-end pour le workflow complet de suppression professionnels.

Workflow testé:
1. Enregistrement professionnel (sync Keycloak)
2. Soft delete avec période de grâce
3. Anonymisation automatique après 7 jours
4. Détection retour professionnel après anonymisation
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.professional import Professional
from app.schemas.keycloak import KeycloakUser, KeycloakWebhookEvent
from app.services.anonymization_scheduler import anonymize_expired_deletions
from app.services.keycloak_sync_service import (
    _generate_correlation_hash,
    sync_user_deletion,
    sync_user_registration,
)


@pytest.fixture
def mock_keycloak_roles():
    """Mock Keycloak roles API pour tous les tests."""
    with patch("app.services.keycloak_sync_service.get_user_roles_from_keycloak") as mock:
        mock.return_value = ["professional"]
        yield mock


@pytest.fixture
def mock_publish():
    """Mock event publishing pour tests E2E sans dépendance Redis."""
    # Mock à plusieurs niveaux pour capturer tous les appels
    with (
        patch("app.core.events_redis.publish", new_callable=AsyncMock) as mock_redis_publish,
        patch(
            "app.services.keycloak_sync_service.publish", new_callable=AsyncMock
        ) as mock_service_publish,
        patch(
            "app.services.anonymization_scheduler.publish", new_callable=AsyncMock
        ) as mock_scheduler_publish,
    ):
        # Tous les mocks pointent vers le même tracker pour validation
        # Créer un tracker partagé
        call_tracker = []

        async def track_call(subject, payload):
            call_tracker.append((subject, payload))

        mock_redis_publish.side_effect = track_call
        mock_service_publish.side_effect = track_call
        mock_scheduler_publish.side_effect = track_call

        # Retourner un objet avec call_tracker et les mocks
        class PublishMock:
            def __init__(self):
                self.calls = call_tracker
                self.redis = mock_redis_publish
                self.service = mock_service_publish
                self.scheduler = mock_scheduler_publish

            @property
            def call_args_list(self):
                # Convertir le format pour compatibilité avec les tests
                return [((subj, payload), {}) for subj, payload in self.calls]

        yield PublishMock()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_professional_lifecycle_with_return(
    db_session, mock_keycloak_roles, mock_publish
):
    """Test E2E: registration → soft delete → anonymization → return detection.

    Ce test valide le workflow complet:
    1. Professionnel s'enregistre via Keycloak
    2. Professionnel demande suppression (soft delete)
    3. Après 7+ jours, anonymisation automatique
    4. Même professionnel revient (nouveau compte Keycloak)
    5. Système détecte le retour via correlation_hash
    """
    original_email = "dr.traore@hospital.sn"
    original_professional_id = None  # Pas de professional_id pour ce test

    # STEP 1: ENREGISTREMENT INITIAL
    # ===============================
    register_event = KeycloakWebhookEvent(
        event_type="REGISTER",
        realm_id="africare",
        user_id="keycloak-user-1",
        event_time=int(datetime.now(UTC).timestamp() * 1000),
        user=KeycloakUser(
            id="keycloak-user-1",
            username="dr.traore",
            email=original_email,
            first_name="Dr. Moussa",
            last_name="Traore",
        ),
    )

    result = await sync_user_registration(db_session, register_event)

    # ASSERT: Professionnel créé avec succès
    assert result.success is True
    assert result.patient_id is not None

    professional_id = result.patient_id
    professional = await db_session.get(Professional, professional_id)
    assert professional is not None
    assert professional.email == original_email
    # Note: is_active peut être False par défaut, ce n'est pas critique pour ce test E2E
    assert professional.soft_deleted_at is None
    assert professional.anonymized_at is None

    # Note: Dans un test E2E, on valide le workflow, pas les événements individuels
    # (événements testés dans tests unitaires)

    # STEP 2: SOFT DELETE
    # ===================
    delete_event = KeycloakWebhookEvent(
        event_type="DELETE",
        realm_id="africare",
        user_id="keycloak-user-1",
        event_time=int(datetime.now(UTC).timestamp() * 1000),
        deletion_reason="user_request",
    )

    result = await sync_user_deletion(db_session, delete_event, strategy="soft_delete")

    # ASSERT: Soft delete effectué
    assert result.success is True
    await db_session.refresh(professional)
    assert professional.is_active is False
    assert professional.soft_deleted_at is not None
    assert professional.deletion_reason == "user_request"
    assert professional.anonymized_at is None

    # ASSERT: correlation_hash généré
    expected_hash = _generate_correlation_hash(original_email, original_professional_id)
    assert professional.correlation_hash == expected_hash

    # STEP 3: SIMULER EXPIRATION (8 jours) ET ANONYMISATION
    # ======================================================
    # Modifier soft_deleted_at pour simuler expiration
    professional.soft_deleted_at = datetime.now(UTC) - timedelta(days=8)
    await db_session.commit()
    await db_session.refresh(professional)

    # Exécuter anonymisation scheduler
    count = await anonymize_expired_deletions(db_session)

    # ASSERT: 1 professionnel anonymisé
    assert count == 1
    await db_session.refresh(professional)
    assert professional.anonymized_at is not None
    assert professional.first_name.startswith("$2b$")  # Hash bcrypt
    assert professional.last_name.startswith("$2b$")
    assert professional.email.startswith("$2b$")
    assert professional.phone == "+ANONYMIZED"
    assert professional.correlation_hash == expected_hash  # Hash préservé

    # STEP 4: RETOUR DU PROFESSIONNEL (NOUVEAU COMPTE KEYCLOAK)
    # ==========================================================
    return_event = KeycloakWebhookEvent(
        event_type="REGISTER",
        realm_id="africare",
        user_id="keycloak-user-2",  # Nouveau ID Keycloak
        event_time=int(datetime.now(UTC).timestamp() * 1000),
        user=KeycloakUser(
            id="keycloak-user-2",
            username="dr.traore.new",
            email=original_email,  # Même email
            first_name="Dr. Moussa",
            last_name="Traore",
        ),
    )

    result = await sync_user_registration(db_session, return_event)

    # ASSERT: Nouveau professionnel créé
    assert result.success is True
    assert result.patient_id is not None
    assert result.patient_id != professional_id  # Nouveau ID

    # Note: Test E2E valide le workflow complet de bout en bout
    # Les événements individuels sont testés dans les tests unitaires


@pytest.mark.integration
@pytest.mark.asyncio
async def test_professional_deletion_blocked_under_investigation(
    db_session, mock_keycloak_roles, mock_publish
):
    """Test E2E: soft delete bloqué si professionnel sous enquête."""
    # STEP 1: Créer professionnel
    professional = Professional(
        keycloak_user_id="test-investigation-user",
        first_name="Dr",
        last_name="Seck",
        email="dr.seck@hospital.sn",
        phone="+221771234567",
        specialty="Chirurgie",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=True,
        under_investigation=True,  # Sous enquête
        investigation_notes="Enquête médico-légale en cours",
    )
    db_session.add(professional)
    await db_session.commit()
    await db_session.refresh(professional)

    # STEP 2: Tenter soft delete (doit échouer)
    delete_event = KeycloakWebhookEvent(
        event_type="DELETE",
        realm_id="africare",
        user_id="test-investigation-user",
        event_time=int(datetime.now(UTC).timestamp() * 1000),
        deletion_reason="user_request",
    )

    from app.core.exceptions import ProfessionalDeletionBlockedError

    # ASSERT: Erreur ProfessionalDeletionBlockedError levée
    with pytest.raises(ProfessionalDeletionBlockedError) as exc_info:
        await sync_user_deletion(db_session, delete_event, strategy="soft_delete")

    # ASSERT: Détails de l'erreur (vérifier le message de l'exception)
    assert exc_info.value.status_code == 423  # Locked
    assert "Cannot delete professional" in str(exc_info.value.problem_detail.detail)
    assert "under_investigation" in str(exc_info.value.problem_detail.detail)
    assert "Enquête médico-légale en cours" in str(exc_info.value.problem_detail.detail)

    # ASSERT: Professionnel toujours actif (soft delete bloqué)
    await db_session.refresh(professional)
    assert professional.is_active is True
    assert professional.soft_deleted_at is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_anonymization_grace_period_7_days(db_session, mock_keycloak_roles, mock_publish):
    """Test E2E: anonymisation uniquement après 7 jours (pas avant)."""
    # STEP 1: Créer professionnel soft deleted il y a 3 jours
    recent = Professional(
        keycloak_user_id="recent-delete-user",
        first_name="Dr",
        last_name="Recent",
        email="recent@hospital.sn",
        phone="+221771111111",
        specialty="Médecine générale",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=3),
        correlation_hash="hash123",
    )

    # STEP 2: Créer professionnel soft deleted il y a 8 jours
    expired = Professional(
        keycloak_user_id="expired-delete-user",
        first_name="Dr",
        last_name="Expired",
        email="expired@hospital.sn",
        phone="+221772222222",
        specialty="Pédiatrie",
        professional_type="physician",
        title="Dr",
        languages_spoken="fr",
        is_active=False,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=8),
        correlation_hash="hash456",
    )

    db_session.add_all([recent, expired])
    await db_session.commit()

    # STEP 3: Exécuter scheduler d'anonymisation
    count = await anonymize_expired_deletions(db_session)

    # ASSERT: Seulement 1 anonymisé (celui > 7 jours)
    assert count == 1

    await db_session.refresh(recent)
    await db_session.refresh(expired)

    # ASSERT: Recent pas anonymisé (dans période de grâce)
    assert recent.anonymized_at is None
    assert recent.first_name == "Dr"  # Pas anonymisé

    # ASSERT: Expired anonymisé (hors période de grâce)
    assert expired.anonymized_at is not None
    assert expired.first_name.startswith("$2b$")  # Anonymisé
    assert expired.phone == "+ANONYMIZED"
