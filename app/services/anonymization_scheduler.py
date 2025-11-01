"""Scheduled task pour anonymisation des professionnels après période de grâce."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.core.events import publish
from app.models.professional import Professional

logger = logging.getLogger(__name__)


async def anonymize_expired_deletions(db: AsyncSession | None = None) -> int:
    """
    Anonymise les professionnels dont la période de grâce a expiré.

    Cette tâche doit être exécutée quotidiennement (via APScheduler ou Celery).

    Logique:
    1. Trouve tous les professionnels avec soft_deleted_at < now() - 7 jours
    2. Pour chaque professionnel, appelle _anonymize()
    3. Set anonymized_at = now()
    4. Publie événement identity.professional.anonymized

    Args:
        db: Session de base de données (optionnel, pour tests)

    Returns:
        Nombre de professionnels anonymisés
    """
    # Créer une session si non fournie (production), sinon utiliser celle fournie (tests)
    if db is None:
        async with async_session_maker() as session:
            return await _anonymize_expired_deletions_impl(session)
    else:
        return await _anonymize_expired_deletions_impl(db)


async def _anonymize_expired_deletions_impl(db: AsyncSession) -> int:
    """Implémentation interne de l'anonymisation."""
    now = datetime.now(UTC)
    expiration_threshold = now - timedelta(days=7)

    # Trouver les suppressions expirées
    result = await db.execute(
        select(Professional).where(
            Professional.soft_deleted_at.isnot(None),
            Professional.soft_deleted_at <= expiration_threshold,
            Professional.anonymized_at.is_(None),  # Pas encore anonymisé
        )
    )
    expired_professionals = result.scalars().all()

    if not expired_professionals:
        logger.info("Aucun professionnel à anonymiser")
        return 0

    logger.info(
        f"Trouvé {len(expired_professionals)} professionnels à anonymiser",
        extra={"count": len(expired_professionals)},
    )

    anonymized_count = 0

    for professional in expired_professionals:
        try:
            # Import _anonymize depuis keycloak_sync_service
            from app.services.keycloak_sync_service import _anonymize_entity

            logger.info(
                f"Anonymisation du professionnel {professional.id} "
                f"(soft deleted le {professional.soft_deleted_at})"
            )

            # Effectuer l'anonymisation
            _anonymize_entity(professional)
            professional.anonymized_at = now

            await db.commit()
            await db.refresh(professional)

            # Publier événement anonymized
            await publish(
                "identity.professional.anonymized",
                {
                    "professional_id": professional.id,
                    "anonymized_at": now.isoformat(),
                    "soft_deleted_at": (
                        professional.soft_deleted_at.isoformat()
                        if professional.soft_deleted_at
                        else None
                    ),
                    "deletion_reason": professional.deletion_reason,
                    "grace_period_days": 7,
                },
            )

            anonymized_count += 1
            logger.info(f"Professionnel {professional.id} anonymisé avec succès")

        except Exception as e:
            logger.error(f"Échec anonymisation professionnel {professional.id}: {e}", exc_info=True)
            await db.rollback()
            continue

    logger.info(f"Anonymisation terminée: {anonymized_count}/{len(expired_professionals)} réussies")
    return anonymized_count


# Exemple d'intégration APScheduler (optionnel, pour référence)
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

def start_scheduler():
    # Exécute quotidiennement à 2:00 AM
    scheduler.add_job(
        anonymize_expired_deletions,
        'cron',
        hour=2,
        minute=0,
        id='anonymize_expired_deletions'
    )
    scheduler.start()
    logger.info("Scheduler d'anonymisation démarré")

def stop_scheduler():
    scheduler.shutdown()
    logger.info("Scheduler d'anonymisation arrêté")
"""
