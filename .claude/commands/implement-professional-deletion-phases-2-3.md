---
name: implement-professional-deletion-phases-2-3
description: Implémenter les Phases 2-3 du feature suppression professionnels avec TDD. Soft delete, anonymisation différée, détection retours, API admin.
---

# Implémenter Phases 2-3 - Amélioration Gestion Suppression Professionnels

## Contexte

Cette commande permet d'implémenter les **Phases 2 et 3** du feature "Amélioration Gestion Suppression Professionnels" dans le microservice `core-africare-identity`.

**Phase 1 (COMPLÉTÉE)** : Fondations (modèle, migration, schémas, corrélation)
**Phases 2-3 (À FAIRE)** : Logique métier, API, tests, documentation

**Branche actuelle** : `feat/professional-deletion-improvements`
**PR associée** : PR #4 (Draft)

## Méthodologie: Test-Driven Development (TDD)

Cette implémentation suit rigoureusement la méthodologie **TDD (Test-Driven Development)** avec le cycle **Red-Green-Refactor**.

### Cycle TDD pour chaque fonctionnalité

```
┌─────────────┐
│   RED       │  1. Écrire le test (qui échoue)
│   ❌        │     - Définir le comportement attendu
└──────┬──────┘     - Le test doit échouer (red)
       │
       ▼
┌─────────────┐
│   GREEN     │  2. Écrire le code minimum (qui passe)
│   ✅        │     - Implémenter juste assez pour passer le test
└──────┬──────┘     - Le test doit réussir (green)
       │
       ▼
┌─────────────┐
│  REFACTOR   │  3. Améliorer le code (sans casser les tests)
│   🔧        │     - Optimiser, clarifier, simplifier
└─────────────┘     - Tous les tests doivent rester verts
```

### Avantages du TDD dans ce projet

1. **Spécification vivante** : Les tests documentent le comportement attendu
2. **Régression zéro** : Les tests existants garantissent qu'on ne casse rien
3. **Design émergent** : L'écriture des tests force une meilleure architecture
4. **Couverture garantie** : Chaque ligne de code a son test correspondant
5. **Confiance élevée** : Refactoring sans peur de casser le comportement

### Application concrète dans les Phases 2-3

**Pour chaque commit** :

1. **RED** : Créer le fichier de test avec les cas de test qui échouent
   ```bash
   # Exemple Commit 4-5
   touch tests/unit/test_soft_delete_workflow.py
   # Écrire test_soft_delete_creates_correlation_hash()
   pytest tests/unit/test_soft_delete_workflow.py  # ❌ FAIL (expected)
   ```

2. **GREEN** : Implémenter le code minimum pour passer les tests
   ```bash
   # Modifier app/services/keycloak_sync_service.py
   pytest tests/unit/test_soft_delete_workflow.py  # ✅ PASS
   ```

3. **REFACTOR** : Améliorer le code sans casser les tests
   ```bash
   # Clarifier noms de variables, extraire fonctions, etc.
   pytest tests/unit/test_soft_delete_workflow.py  # ✅ PASS (still green)
   ```

### Ordre d'implémentation TDD par commit

**Commit 4-5 (Soft Delete)** :
- RED: `tests/unit/test_soft_delete_workflow.py` (3 tests)
- GREEN: `sync_user_deletion()` modifié
- REFACTOR: Extraction event publishing dans helpers si nécessaire

**Commit 6 (Anonymisation)** :
- RED: `tests/unit/test_anonymize_expired_deletions.py` (2 tests)
- GREEN: `app/services/anonymization_scheduler.py`
- REFACTOR: Optimisation requêtes SQL

**Commit 7 (Détection Retours)** :
- RED: `tests/unit/test_returning_professional_detection.py` (1 test)
- GREEN: `sync_user_registration()` modifié
- REFACTOR: Amélioration logging

**Commit 8 (API Admin)** :
- RED: `tests/unit/test_professional_admin_endpoints.py` (4 tests)
- GREEN: `app/api/v1/endpoints/professional_admin.py`
- REFACTOR: Validation et error handling

**Commit 9 (Tests Intégration)** :
- RED: `tests/integration/test_deletion_workflow_end_to_end.py` (1 test E2E)
- GREEN: Corrections éventuelles découvertes par intégration
- REFACTOR: Cleanup et optimisations finales

## État Actuel (Phase 1 Complétée)

### Commits déjà créés

1. `630d153` - Model + Migration Alembic
2. `31b8ad9` - Schemas + Exceptions RFC 9457
3. `492e2fc` - Système de Corrélation + Tests
4. `bb6c1d8` - Documentation (docs/professional-deletion-improvements.md)

### Nouveaux champs Professional

```python
# app/models/professional.py
under_investigation: Mapped[bool] = mapped_column(
    nullable=False, default=False, index=True,
    comment="Professionnel sous enquête médico-légale (bloque suppression)"
)
investigation_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
correlation_hash: Mapped[str | None] = mapped_column(
    String(64), nullable=True, index=True,
    comment="Hash SHA-256 de email+professional_id pour corrélation anonymisée"
)
soft_deleted_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True, index=True,
    comment="Date de soft delete (début période de grâce 7 jours)"
)
anonymized_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True, index=True,
    comment="Date d'anonymisation définitive (après période de grâce)"
)
deletion_reason: Mapped[Literal[...] | None] = mapped_column(String(50), nullable=True)
```

### Fonctions de corrélation existantes

```python
# app/services/keycloak_sync_service.py

def _generate_correlation_hash(email: str, professional_id: str | None) -> str:
    """Generate SHA-256 deterministic hash for correlation."""
    import hashlib
    from app.core.config import settings
    salt = getattr(settings, "CORRELATION_HASH_SALT", "africare-identity-salt-v1")
    hash_input = f"{email}|{professional_id or ''}|{salt}"
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

async def _check_returning_professional(
    db: AsyncSession, email: str, professional_id: str | None
) -> Professional | None:
    """Check if anonymized professional returns by correlation hash."""
    correlation_hash = _generate_correlation_hash(email, professional_id)
    result = await db.execute(
        select(Professional).where(
            Professional.correlation_hash == correlation_hash,
            Professional.anonymized_at.isnot(None)
        )
    )
    return result.scalar_one_or_none()
```

### Exception déjà créée

```python
# app/core/exceptions.py
class ProfessionalDeletionBlockedError(RFC9457Exception):
    """Exception HTTP 423 Locked quand suppression bloquée."""
    def __init__(self, professional_id: int, reason: str = "under_investigation",
                 investigation_notes: str | None = None):
        super().__init__(
            status_code=423,
            title="Professional Deletion Blocked",
            detail=f"Cannot delete professional {professional_id}: {reason}",
            type="https://africare.app/errors/deletion-blocked",
            instance=f"/api/v1/professionals/{professional_id}"
        )
```

### Schémas déjà créés

```python
# app/schemas/professional.py
DeletionReason = Literal[
    "user_request", "admin_termination", "professional_revocation",
    "gdpr_compliance", "prolonged_inactivity"
]

class ProfessionalDeletionRequest(BaseModel):
    deletion_reason: DeletionReason
    investigation_check_override: bool = False
    notes: str | None = Field(None, max_length=1000)

class ProfessionalRestoreRequest(BaseModel):
    restore_reason: NonEmptyStr
    notes: str | None = Field(None, max_length=1000)

class ProfessionalInvestigationUpdate(BaseModel):
    under_investigation: bool
    investigation_notes: str | None = Field(None, max_length=1000)
```

---

## Phase 2 : Logique Métier (Commits 4-7)

### Commit 4-5 : Soft Delete avec Période de Grâce

**Méthodologie TDD** : 🔴 RED → 🟢 GREEN → 🔧 REFACTOR

1. **RED** : Écrire `tests/unit/test_soft_delete_workflow.py` (3 tests qui échouent)
2. **GREEN** : Modifier `sync_user_deletion()` pour passer les tests
3. **REFACTOR** : Optimiser event publishing et error handling

---

**Fichier** : `app/services/keycloak_sync_service.py`
**Fonction à modifier** : `sync_user_deletion()`

**Modifications à apporter** :

1. **Vérifier `under_investigation`** avant toute suppression
2. **Générer `correlation_hash`** AVANT anonymisation
3. **Soft delete** : `is_active=False`, `soft_deleted_at=now()`
4. **Publier événement** `identity.professional.soft_deleted`
5. **Publier événement** `identity.professional.appointments_action_required`

**Code à implémenter** :

```python
@subscribe("keycloak.user.DELETE")
async def sync_user_deletion(payload: dict) -> None:
    """
    Handle user deletion from Keycloak with soft delete and grace period.

    Workflow:
    1. Check if professional under_investigation (block if true)
    2. Generate correlation_hash BEFORE anonymization
    3. Soft delete: is_active=False, soft_deleted_at=now()
    4. Publish events for appointments and other services
    5. Actual anonymization happens after 7 days (scheduled task)
    """
    from datetime import UTC, datetime, timedelta
    from app.core.exceptions import ProfessionalDeletionBlockedError

    logger.info("Received Keycloak DELETE event", extra={"payload": payload})

    async with get_session_from_context() as db:
        keycloak_user_id = payload.get("userId")
        if not keycloak_user_id:
            logger.warning("DELETE event missing userId")
            return

        # Find professional by Keycloak user ID
        result = await db.execute(
            select(Professional).where(Professional.keycloak_user_id == keycloak_user_id)
        )
        professional = result.scalar_one_or_none()

        if not professional:
            logger.warning(f"Professional not found for Keycloak user {keycloak_user_id}")
            return

        # CHECK 1: Block if under investigation
        if professional.under_investigation:
            logger.error(
                f"Cannot delete professional {professional.id}: under_investigation=True",
                extra={"investigation_notes": professional.investigation_notes}
            )
            raise ProfessionalDeletionBlockedError(
                professional_id=professional.id,
                reason="under_investigation",
                investigation_notes=professional.investigation_notes
            )

        # CHECK 2: Already soft deleted or anonymized
        if professional.soft_deleted_at is not None:
            logger.warning(f"Professional {professional.id} already soft deleted")
            return
        if professional.anonymized_at is not None:
            logger.warning(f"Professional {professional.id} already anonymized")
            return

        # STEP 1: Generate correlation_hash BEFORE anonymization
        if not professional.correlation_hash:
            professional.correlation_hash = _generate_correlation_hash(
                professional.email,
                professional.professional_id
            )
            logger.info(
                f"Generated correlation_hash for professional {professional.id}",
                extra={"correlation_hash": professional.correlation_hash}
            )

        # STEP 2: Soft delete (grace period starts)
        now = datetime.now(UTC)
        grace_period_end = now + timedelta(days=7)

        professional.is_active = False
        professional.soft_deleted_at = now
        professional.deletion_reason = payload.get("deletion_reason", "user_request")

        await db.commit()
        await db.refresh(professional)

        logger.info(
            f"Professional {professional.id} soft deleted with 7-day grace period",
            extra={
                "soft_deleted_at": now.isoformat(),
                "grace_period_end": grace_period_end.isoformat()
            }
        )

        # STEP 3: Publish soft_deleted event
        await publish("identity.professional.soft_deleted", {
            "professional_id": professional.id,
            "keycloak_user_id": keycloak_user_id,
            "soft_deleted_at": now.isoformat(),
            "anonymization_scheduled_at": grace_period_end.isoformat(),
            "grace_period_days": 7,
            "deletion_reason": professional.deletion_reason,
            "specialty": professional.specialty,
            "professional_type": professional.professional_type
        })

        # STEP 4: Publish appointment action required event
        await publish("identity.professional.appointments_action_required", {
            "professional_id": professional.id,
            "keycloak_user_id": keycloak_user_id,
            "action": "pending_reassignment",
            "grace_period_end": grace_period_end.isoformat(),
            "instructions": {
                "days_0_to_7": "maintain_appointments",
                "day_7": "propose_reassignment",
                "fallback": "cancel_with_notification"
            },
            "professional_info": {
                "full_name": f"{professional.title} {professional.first_name} {professional.last_name}",
                "specialty": professional.specialty,
                "professional_type": professional.professional_type
            }
        })

        logger.info(
            f"Published soft deletion events for professional {professional.id}",
            extra={"grace_period_end": grace_period_end.isoformat()}
        )
```

**Tests à créer** : `tests/unit/test_soft_delete_workflow.py`

```python
"""Tests pour le workflow de soft delete avec période de grâce."""

import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from app.models.professional import Professional
from app.services.keycloak_sync_service import sync_user_deletion, _generate_correlation_hash
from app.core.exceptions import ProfessionalDeletionBlockedError


@pytest.mark.asyncio
async def test_soft_delete_creates_correlation_hash(db_session):
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
        is_active=True
    )
    db_session.add(professional)
    await db_session.commit()
    await db_session.refresh(professional)

    # Simulate DELETE event
    payload = {"userId": "test-delete-123", "deletion_reason": "user_request"}
    await sync_user_deletion(payload)

    # Verify
    await db_session.refresh(professional)
    assert professional.is_active is False
    assert professional.soft_deleted_at is not None
    assert professional.correlation_hash is not None
    assert professional.anonymized_at is None  # Not yet anonymized


@pytest.mark.asyncio
async def test_soft_delete_blocked_under_investigation(db_session):
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
        is_active=True
    )
    db_session.add(professional)
    await db_session.commit()

    # Attempt soft delete
    payload = {"userId": "test-investigation-123"}

    with pytest.raises(ProfessionalDeletionBlockedError) as exc_info:
        await sync_user_deletion(payload)

    assert exc_info.value.status_code == 423
    assert "under_investigation" in str(exc_info.value.problem_detail.detail)

    # Verify professional not deleted
    await db_session.refresh(professional)
    assert professional.is_active is True
    assert professional.soft_deleted_at is None


@pytest.mark.asyncio
async def test_soft_delete_grace_period_7_days(db_session):
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
        is_active=True
    )
    db_session.add(professional)
    await db_session.commit()

    # Soft delete
    now = datetime.now(UTC)
    payload = {"userId": "test-grace-123", "deletion_reason": "gdpr_compliance"}
    await sync_user_deletion(payload)

    await db_session.refresh(professional)
    grace_period_end = professional.soft_deleted_at + timedelta(days=7)

    assert professional.soft_deleted_at is not None
    assert abs((grace_period_end - professional.soft_deleted_at).days) == 7
    assert professional.deletion_reason == "gdpr_compliance"
```

### Commit 6 : Anonymisation Différée (Scheduled Task)

**Méthodologie TDD** : 🔴 RED → 🟢 GREEN → 🔧 REFACTOR

1. **RED** : Écrire `tests/unit/test_anonymize_expired_deletions.py` (2 tests qui échouent)
2. **GREEN** : Créer `app/services/anonymization_scheduler.py` pour passer les tests
3. **REFACTOR** : Optimiser requêtes SQL et error handling

---

**Nouveau fichier** : `app/services/anonymization_scheduler.py`

**Code à créer** :

```python
"""Scheduled task for anonymizing professionals after grace period."""

import logging
from datetime import UTC, datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.core.events import publish
from app.models.professional import Professional

logger = logging.getLogger(__name__)


async def anonymize_expired_deletions() -> int:
    """
    Anonymize professionals whose soft_delete grace period has expired.

    This task should be scheduled to run daily (e.g., via APScheduler or Celery).

    Logic:
    1. Find all professionals with soft_deleted_at < now() - 7 days
    2. For each professional, call _anonymize()
    3. Set anonymized_at = now()
    4. Publish identity.professional.anonymized event

    Returns:
        Number of professionals anonymized
    """
    async with async_session_maker() as db:
        now = datetime.now(UTC)
        expiration_threshold = now - timedelta(days=7)

        # Find expired soft deletions
        result = await db.execute(
            select(Professional).where(
                Professional.soft_deleted_at.isnot(None),
                Professional.soft_deleted_at <= expiration_threshold,
                Professional.anonymized_at.is_(None)  # Not yet anonymized
            )
        )
        expired_professionals = result.scalars().all()

        if not expired_professionals:
            logger.info("No professionals found for anonymization")
            return 0

        logger.info(
            f"Found {len(expired_professionals)} professionals for anonymization",
            extra={"count": len(expired_professionals)}
        )

        anonymized_count = 0

        for professional in expired_professionals:
            try:
                # Import _anonymize from keycloak_sync_service
                from app.services.keycloak_sync_service import _anonymize

                logger.info(
                    f"Anonymizing professional {professional.id} (soft deleted on {professional.soft_deleted_at})"
                )

                # Perform anonymization
                _anonymize(professional)
                professional.anonymized_at = now

                await db.commit()
                await db.refresh(professional)

                # Publish anonymized event
                await publish("identity.professional.anonymized", {
                    "professional_id": professional.id,
                    "anonymized_at": now.isoformat(),
                    "soft_deleted_at": professional.soft_deleted_at.isoformat(),
                    "deletion_reason": professional.deletion_reason,
                    "grace_period_days": 7
                })

                anonymized_count += 1
                logger.info(f"Successfully anonymized professional {professional.id}")

            except Exception as e:
                logger.error(
                    f"Failed to anonymize professional {professional.id}: {e}",
                    exc_info=True
                )
                await db.rollback()
                continue

        logger.info(
            f"Anonymization complete: {anonymized_count}/{len(expired_professionals)} succeeded"
        )
        return anonymized_count


# APScheduler integration example (optional, for reference)
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

def start_scheduler():
    # Run daily at 2:00 AM
    scheduler.add_job(
        anonymize_expired_deletions,
        'cron',
        hour=2,
        minute=0,
        id='anonymize_expired_deletions'
    )
    scheduler.start()
    logger.info("Anonymization scheduler started")

def stop_scheduler():
    scheduler.shutdown()
    logger.info("Anonymization scheduler stopped")
"""
```

**Tests à créer** : `tests/unit/test_anonymize_expired_deletions.py`

```python
"""Tests pour l'anonymisation différée après période de grâce."""

import pytest
from datetime import UTC, datetime, timedelta
from app.models.professional import Professional
from app.services.anonymization_scheduler import anonymize_expired_deletions


@pytest.mark.asyncio
async def test_anonymize_expired_professionals(db_session):
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
        correlation_hash="abc123"
    )
    db_session.add(professional)
    await db_session.commit()

    # Run anonymization task
    count = await anonymize_expired_deletions()

    assert count == 1

    # Verify anonymization
    await db_session.refresh(professional)
    assert professional.anonymized_at is not None
    assert "[ANONYMIZED_HASH_" in professional.first_name
    assert "[ANONYMIZED_HASH_" in professional.last_name
    assert "[ANONYMIZED_HASH_" in professional.email


@pytest.mark.asyncio
async def test_no_anonymization_within_grace_period(db_session):
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
        soft_deleted_at=recent_date
    )
    db_session.add(professional)
    await db_session.commit()

    # Run anonymization task
    count = await anonymize_expired_deletions()

    assert count == 0

    # Verify NOT anonymized
    await db_session.refresh(professional)
    assert professional.anonymized_at is None
    assert professional.first_name == "Dr"  # Not anonymized yet
```

### Commit 7 : Détection des Retours

**Méthodologie TDD** : 🔴 RED → 🟢 GREEN → 🔧 REFACTOR

1. **RED** : Écrire `tests/unit/test_returning_professional_detection.py` (1 test qui échoue)
2. **GREEN** : Modifier `sync_user_registration()` pour passer le test
3. **REFACTOR** : Améliorer logging et event publishing

---

**Fichier** : `app/services/keycloak_sync_service.py`
**Fonction à modifier** : `sync_user_registration()`

**Modifications à apporter** :

```python
@subscribe("keycloak.user.REGISTER")
async def sync_user_registration(payload: dict) -> None:
    """
    Handle new user registration from Keycloak with returning professional detection.

    Checks if this is a returning professional (previously anonymized) using
    correlation hash before creating new profile.
    """
    logger.info("Received Keycloak REGISTER event", extra={"payload": payload})

    async with get_session_from_context() as db:
        # ... existing code for extracting event data ...

        # NEW: Check if returning professional
        returning = await _check_returning_professional(
            db,
            event.email,
            event.professional_id
        )

        if returning:
            logger.warning(
                f"Detected returning professional: {event.email}",
                extra={
                    "new_keycloak_user_id": event.user_id,
                    "previous_professional_id": returning.id,
                    "anonymized_at": returning.anonymized_at.isoformat() if returning.anonymized_at else None
                }
            )

            # Publish returning detected event
            await publish("identity.professional.returning_detected", {
                "new_keycloak_user_id": event.user_id,
                "previous_professional_id": returning.id,
                "anonymized_at": returning.anonymized_at.isoformat() if returning.anonymized_at else None,
                "correlation_hash": returning.correlation_hash,
                "email": event.email,
                "professional_id": event.professional_id,
                "detection_timestamp": datetime.now(UTC).isoformat()
            })

        # IMPORTANT: Create NEW profile (anonymization is IRREVERSIBLE)
        # ... existing code for creating patient/professional ...
```

**Tests à créer** : `tests/unit/test_returning_professional_detection.py`

```python
"""Tests pour la détection de retour de professionnels anonymisés."""

import pytest
from datetime import UTC, datetime, timedelta
from app.models.professional import Professional
from app.services.keycloak_sync_service import (
    sync_user_registration,
    _generate_correlation_hash
)


@pytest.mark.asyncio
async def test_detect_returning_professional(db_session):
    """Test: détecte un professionnel qui revient après anonymisation."""
    # Create anonymized professional
    email = "dr.returning@hospital.sn"
    professional_id = "CNOM99999"
    correlation_hash = _generate_correlation_hash(email, professional_id)

    old_professional = Professional(
        keycloak_user_id="old-user-id",
        first_name="[ANONYMIZED_HASH_abc]",
        last_name="[ANONYMIZED_HASH_def]",
        email="[ANONYMIZED_HASH_ghi]",
        phone="+221000000000",
        specialty="Cardiologie",
        professional_type="physician",
        title="Dr",
        is_active=False,
        correlation_hash=correlation_hash,
        soft_deleted_at=datetime.now(UTC) - timedelta(days=10),
        anonymized_at=datetime.now(UTC) - timedelta(days=3)
    )
    db_session.add(old_professional)
    await db_session.commit()

    # New registration with same email + professional_id
    payload = {
        "userId": "new-user-id",
        "email": email,
        "professional_id": professional_id,
        "firstName": "Amadou",
        "lastName": "Diop"
    }

    await sync_user_registration(payload)

    # Verify new profile created (anonymization irreversible)
    from sqlalchemy import select
    result = await db_session.execute(
        select(Professional).where(Professional.keycloak_user_id == "new-user-id")
    )
    new_professional = result.scalar_one_or_none()

    assert new_professional is not None
    assert new_professional.id != old_professional.id  # Different profile
    assert new_professional.email == email  # Not anonymized
```

---

## Phase 3 : API et Documentation (Commits 8-10)

### Commit 8 : Endpoints Administrateur

**Méthodologie TDD** : 🔴 RED → 🟢 GREEN → 🔧 REFACTOR

1. **RED** : Écrire `tests/unit/test_professional_admin_endpoints.py` (4 tests qui échouent)
2. **GREEN** : Créer `app/api/v1/endpoints/professional_admin.py` pour passer les tests
3. **REFACTOR** : Améliorer validation et error handling RFC 9457

---

**Nouveau fichier** : `app/api/v1/endpoints/professional_admin.py`

**Code à créer** :

```python
"""Admin endpoints for professional deletion management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.events import publish
from app.core.exceptions import NotFoundError, ProfessionalDeletionBlockedError
from app.models.professional import Professional
from app.schemas.professional import (
    ProfessionalInvestigationUpdate,
    ProfessionalRestoreRequest,
    ProfessionalResponse
)

router = APIRouter()


@router.post("/{professional_id}/investigate", response_model=ProfessionalResponse)
async def set_investigation_status(
    professional_id: int,
    update: ProfessionalInvestigationUpdate,
    db: AsyncSession = Depends(get_session)
) -> ProfessionalResponse:
    """
    Set investigation status for a professional (admin only).

    When under_investigation=True, deletion is blocked until cleared.
    """
    result = await db.execute(
        select(Professional).where(Professional.id == professional_id)
    )
    professional = result.scalar_one_or_none()

    if not professional:
        raise NotFoundError(
            detail=f"Professional {professional_id} not found",
            instance=f"/api/v1/professionals/{professional_id}/investigate"
        )

    # Update investigation status
    professional.under_investigation = update.under_investigation
    professional.investigation_notes = update.investigation_notes

    await db.commit()
    await db.refresh(professional)

    # Publish event
    await publish("identity.professional.investigation_updated", {
        "professional_id": professional_id,
        "under_investigation": update.under_investigation,
        "investigation_notes": update.investigation_notes
    })

    return ProfessionalResponse.model_validate(professional)


@router.post("/{professional_id}/restore", response_model=ProfessionalResponse)
async def restore_professional(
    professional_id: int,
    request: ProfessionalRestoreRequest,
    db: AsyncSession = Depends(get_session)
) -> ProfessionalResponse:
    """
    Restore a soft-deleted professional within grace period (admin only).

    Only possible if:
    - soft_deleted_at is not None
    - anonymized_at is None (not yet anonymized)
    - Within 7-day grace period
    """
    from datetime import UTC, datetime, timedelta

    result = await db.execute(
        select(Professional).where(Professional.id == professional_id)
    )
    professional = result.scalar_one_or_none()

    if not professional:
        raise NotFoundError(
            detail=f"Professional {professional_id} not found",
            instance=f"/api/v1/professionals/{professional_id}/restore"
        )

    # Validation
    if professional.soft_deleted_at is None:
        raise HTTPException(
            status_code=400,
            detail="Professional is not soft deleted"
        )

    if professional.anonymized_at is not None:
        raise HTTPException(
            status_code=400,
            detail="Cannot restore anonymized professional (irreversible)"
        )

    # Check grace period (7 days)
    now = datetime.now(UTC)
    grace_period_end = professional.soft_deleted_at + timedelta(days=7)
    if now > grace_period_end:
        raise HTTPException(
            status_code=400,
            detail=f"Grace period expired on {grace_period_end.isoformat()}"
        )

    # Restore professional
    professional.is_active = True
    professional.soft_deleted_at = None
    professional.deletion_reason = None

    await db.commit()
    await db.refresh(professional)

    # Publish event
    await publish("identity.professional.restored", {
        "professional_id": professional_id,
        "restored_at": now.isoformat(),
        "restore_reason": request.restore_reason,
        "notes": request.notes
    })

    return ProfessionalResponse.model_validate(professional)
```

**Intégrer dans** : `app/api/v1/api.py`

```python
from app.api.v1.endpoints import professional_admin

router.include_router(
    professional_admin.router,
    prefix="/professionals",
    tags=["professionals-admin"]
)
```

**Tests à créer** : `tests/unit/test_professional_admin_endpoints.py`

### Commit 9 : Tests Intégration Complets

**Méthodologie TDD** : 🔴 RED → 🟢 GREEN → 🔧 REFACTOR

1. **RED** : Écrire `tests/integration/test_deletion_workflow_end_to_end.py` (1 test E2E qui échoue)
2. **GREEN** : Corriger les bugs découverts par le test d'intégration
3. **REFACTOR** : Cleanup final et optimisations

---

**Créer** : `tests/integration/test_deletion_workflow_end_to_end.py`

```python
"""Tests d'intégration end-to-end pour le workflow de suppression."""

import pytest
from datetime import UTC, datetime, timedelta
from app.models.professional import Professional
from app.services.keycloak_sync_service import sync_user_deletion
from app.services.anonymization_scheduler import anonymize_expired_deletions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_deletion_workflow(db_session):
    """Test complet: soft delete → grace period → anonymisation."""
    # 1. Create professional
    professional = Professional(
        keycloak_user_id="test-workflow-123",
        first_name="Dr",
        last_name="Complete",
        email="dr.complete@hospital.sn",
        phone="+221771234567",
        specialty="Test",
        professional_type="physician",
        title="Dr",
        is_active=True
    )
    db_session.add(professional)
    await db_session.commit()
    professional_id = professional.id

    # 2. Soft delete
    await sync_user_deletion({"userId": "test-workflow-123"})
    await db_session.refresh(professional)

    assert professional.is_active is False
    assert professional.soft_deleted_at is not None
    assert professional.anonymized_at is None

    # 3. Simulate expiration (force date)
    professional.soft_deleted_at = datetime.now(UTC) - timedelta(days=8)
    await db_session.commit()

    # 4. Run anonymization
    count = await anonymize_expired_deletions()
    assert count == 1

    # 5. Verify anonymization
    await db_session.refresh(professional)
    assert professional.anonymized_at is not None
    assert "[ANONYMIZED_HASH_" in professional.first_name
```

### Commit 10 : Documentation Finale

**Mettre à jour** : `docs/professional-deletion-improvements.md`

- Marquer Phases 2-3 comme complétées
- Ajouter diagrammes de séquence (si besoin)
- Instructions de déploiement (scheduler APScheduler)

**Mettre à jour** : `CLAUDE.md`

- Ajouter section sur la gestion de suppression
- Documenter les événements publiés
- Expliquer le scheduler

---

## Instructions d'Exécution

### Prérequis

1. Être sur la branche `feat/professional-deletion-improvements`
2. Phase 1 déjà complétée et testée
3. Services Docker actifs (PostgreSQL, Redis)

### Workflow de Commit (TDD)

Pour chaque commit (4-10), suivre **rigoureusement** le cycle TDD :

#### Phase RED (Test qui échoue)

1. **Créer le fichier de test** avec les cas de test
   ```bash
   touch tests/unit/test_[nom_fonctionnalite].py
   ```

2. **Écrire les tests AVANT le code**
   - Définir le comportement attendu
   - Écrire les assertions
   - Utiliser des mocks si nécessaire

3. **Vérifier que les tests échouent** (RED)
   ```bash
   pytest tests/unit/test_[nom_fonctionnalite].py -v
   # ❌ DOIT échouer (comportement pas encore implémenté)
   ```

#### Phase GREEN (Code minimal qui passe)

4. **Implémenter le code minimum** pour passer les tests
   - Ne pas sur-architecturer
   - Juste assez pour que les tests passent

5. **Vérifier que les tests passent** (GREEN)
   ```bash
   pytest tests/unit/test_[nom_fonctionnalite].py -v
   # ✅ DOIT réussir
   ```

6. **Exécuter TOUS les tests** pour détecter régressions
   ```bash
   make test
   # ✅ Tous les tests doivent passer
   ```

#### Phase REFACTOR (Amélioration sans casser)

7. **Refactorer le code** (si nécessaire)
   - Améliorer la lisibilité
   - Optimiser les performances
   - Extraire des fonctions helpers

8. **Vérifier que les tests restent verts**
   ```bash
   make test
   # ✅ Aucune régression introduite
   ```

9. **Vérifier le linting** : `make lint`

#### Commit

10. **Créer le commit avec message détaillé** (voir template ci-dessous)
11. **Pousser vers origin** : `git push origin feat/professional-deletion-improvements`

**IMPORTANT** : Ne JAMAIS passer à la phase GREEN sans avoir d'abord écrit les tests (RED). C'est l'essence même du TDD.

### Template Message de Commit

```bash
# Générer ID aléatoire
COMMIT_ID=$(shuf -i 1000-9999 -n 1)

# Écrire message dans fichier temporaire
cat > /tmp/commit_message_${COMMIT_ID}.md <<'EOF'
feat(deletion): [titre du commit]

CONTEXTE :
[Explication du besoin]

SOLUTION IMPLÉMENTÉE :
[Détails de l'implémentation]

FICHIERS MODIFIÉS :
- [liste des fichiers]

TESTS AJOUTÉS :
- [liste des tests]
EOF

# Committer
git add -A && \
git commit -F /tmp/commit_message_${COMMIT_ID}.md && \
rm /tmp/commit_message_${COMMIT_ID}.md
```

### Validation Finale

Après le commit 10:

1. **Tous les tests doivent passer** : `make test-all`
2. **Couverture ≥ 80%** : `pytest --cov=app --cov-report=term`
3. **Linting propre** : `make lint`
4. **Mettre à jour PR #4** : Retirer le status Draft
5. **Demander review** : Assigner reviewers

### Configuration du Scheduler (Déploiement)

Ajouter dans `pyproject.toml`:

```toml
[tool.poetry.dependencies]
apscheduler = "^3.10.4"
```

Ajouter dans `app/main.py`:

```python
from app.services.anonymization_scheduler import start_scheduler, stop_scheduler

@app.on_event("startup")
async def startup_scheduler():
    start_scheduler()

@app.on_event("shutdown")
async def shutdown_scheduler():
    stop_scheduler()
```

---

## Événements Publiés (Récapitulatif)

| Événement | Moment | Payload Clés |
|-----------|--------|--------------|
| `identity.professional.soft_deleted` | Soft delete (début période grâce) | `professional_id`, `grace_period_end`, `deletion_reason` |
| `identity.professional.appointments_action_required` | Soft delete | `action: "pending_reassignment"`, `instructions` |
| `identity.professional.anonymized` | Fin période grâce (7j) | `professional_id`, `anonymized_at` |
| `identity.professional.returning_detected` | Registration avec correlation match | `previous_professional_id`, `correlation_hash` |
| `identity.professional.investigation_updated` | Admin change investigation status | `under_investigation` |
| `identity.professional.restored` | Admin restore (< 7j) | `restored_at`, `restore_reason` |

---

## Points d'Attention

1. **Scheduler APScheduler** : Nécessite configuration en production (Celery possible aussi)
2. **Checkpoints Event Hub** : Vérifier que les événements ne sont pas retraités
3. **Tests Intégration** : Utiliser `docker-compose.test.yaml` pour isolation
4. **Rollback** : En cas d'erreur, possibilité de restaurer durant 7 jours
5. **RGPD** : Anonymisation irréversible après 7 jours, conforme Article 17

---

## Ressources

- **Documentation complète** : `docs/professional-deletion-improvements.md`
- **Tests corrélation existants** : `tests/unit/test_correlation_hash.py`
- **Migration Alembic** : `alembic/versions/23f6c23e1f1b_*.py`
- **Exception** : `app/core/exceptions.py` ligne 109
- **Schémas** : `app/schemas/professional.py` lignes 229-279

---

**Note** : Cette commande préserve le contexte complet pour reprendre le développement ultérieurement sans perte d'information.
