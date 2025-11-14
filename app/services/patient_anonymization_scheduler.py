"""Scheduled task pour anonymisation des patients après période de grâce."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.core.events import publish
from app.models.patient import Patient

logger = logging.getLogger(__name__)


async def anonymize_expired_patient_deletions(db: AsyncSession | None = None) -> int:
    """
    Anonymise les patients dont la période de grâce a expiré.

    Cette tâche doit être exécutée quotidiennement (via APScheduler ou Celery).

    Logique:
    1. Trouve tous les patients avec soft_deleted_at < now() - 7 jours
    2. Pour chaque patient, appelle _anonymize_entity()
    3. Set anonymized_at = now()
    4. Publie événement identity.patient.anonymized

    Args:
        db: Session de base de données (optionnel, pour tests)

    Returns:
        Nombre de patients anonymisés
    """
    # Créer une session si non fournie (production), sinon utiliser celle fournie (tests)
    if db is None:
        async with async_session_maker() as session:
            return await _anonymize_expired_patient_deletions_impl(session)
    else:
        return await _anonymize_expired_patient_deletions_impl(db)


async def _anonymize_expired_patient_deletions_impl(db: AsyncSession) -> int:
    """Implémentation interne de l'anonymisation."""
    now = datetime.now(UTC)
    expiration_threshold = now - timedelta(days=7)

    # Trouver les suppressions expirées
    result = await db.execute(
        select(Patient).where(
            Patient.soft_deleted_at.isnot(None),
            Patient.soft_deleted_at <= expiration_threshold,
            Patient.anonymized_at.is_(None),  # Pas encore anonymisé
        )
    )
    expired_patients = result.scalars().all()

    if not expired_patients:
        logger.info("Aucun patient à anonymiser")
        return 0

    logger.info(
        f"Trouvé {len(expired_patients)} patients à anonymiser",
        extra={"count": len(expired_patients)},
    )

    anonymized_count = 0

    for patient in expired_patients:
        try:
            # Import _anonymize_entity depuis keycloak_sync_service
            from app.services.keycloak_sync_service import _anonymize_entity

            logger.info(
                f"Anonymisation du patient {patient.id} (soft deleted le {patient.soft_deleted_at})"
            )

            # Effectuer l'anonymisation
            _anonymize_entity(patient)
            patient.anonymized_at = now

            await db.commit()
            await db.refresh(patient)

            # Publier événement anonymized
            await publish(
                "identity.patient.anonymized",
                {
                    "patient_id": patient.id,
                    "anonymized_at": now.isoformat(),
                    "soft_deleted_at": (
                        patient.soft_deleted_at.isoformat() if patient.soft_deleted_at else None
                    ),
                    "deletion_reason": patient.deletion_reason,
                    "grace_period_days": 7,
                },
            )

            anonymized_count += 1
            logger.info(f"Patient {patient.id} anonymisé avec succès")

        except Exception as e:
            logger.error(f"Échec anonymisation patient {patient.id}: {e}", exc_info=True)
            await db.rollback()
            continue

    logger.info(f"Anonymisation terminée: {anonymized_count}/{len(expired_patients)} réussies")
    return anonymized_count


# Exemple d'intégration APScheduler (optionnel, pour référence)
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

def start_patient_anonymization_scheduler():
    # Exécute quotidiennement à 2:00 AM
    scheduler.add_job(
        anonymize_expired_patient_deletions,
        'cron',
        hour=2,
        minute=0,
        id='anonymize_expired_patient_deletions'
    )
    scheduler.start()
    logger.info("Scheduler d'anonymisation patients démarré")

def stop_scheduler():
    scheduler.shutdown()
    logger.info("Scheduler d'anonymisation patients arrêté")
"""
