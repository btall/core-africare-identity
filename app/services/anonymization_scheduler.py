"""Scheduled task pour anonymisation des professionnels après période de grâce.

Architecture hybride FHIR + PostgreSQL:
- Requête sur ProfessionalGdprMetadata pour trouver les suppressions expirées
- Anonymisation des données FHIR (Practitioner resource)
- Mise à jour de gdpr.anonymized_at dans PostgreSQL
"""

import logging
from datetime import UTC, datetime, timedelta

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.core.events import publish
from app.infrastructure.fhir.client import get_fhir_client
from app.infrastructure.fhir.identifiers import KEYCLOAK_SYSTEM, PROFESSIONAL_LICENSE_SYSTEM
from app.models.gdpr_metadata import ProfessionalGdprMetadata

logger = logging.getLogger(__name__)


async def anonymize_expired_deletions(db: AsyncSession | None = None) -> int:
    """
    Anonymise les professionnels dont la période de grâce a expiré.

    Cette tâche doit être exécutée quotidiennement (via APScheduler ou Celery).

    Architecture hybride:
    - Query sur ProfessionalGdprMetadata (soft_deleted_at, anonymized_at)
    - Anonymisation des données FHIR Practitioner
    - Mise à jour de gdpr.anonymized_at

    Logique:
    1. Trouve tous les professionnels avec soft_deleted_at < now() - 7 jours
    2. Pour chaque professionnel, anonymise la ressource FHIR
    3. Set anonymized_at = now() dans GDPR metadata
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

    # Trouver les suppressions expirées dans GDPR metadata
    result = await db.execute(
        select(ProfessionalGdprMetadata).where(
            ProfessionalGdprMetadata.soft_deleted_at.isnot(None),
            ProfessionalGdprMetadata.soft_deleted_at <= expiration_threshold,
            ProfessionalGdprMetadata.anonymized_at.is_(None),  # Pas encore anonymisé
        )
    )
    expired_records = result.scalars().all()

    if not expired_records:
        logger.info("Aucun professionnel à anonymiser")
        return 0

    logger.info(
        f"Trouvé {len(expired_records)} professionnels à anonymiser",
        extra={"count": len(expired_records)},
    )

    # Récupérer client FHIR
    fhir_client = get_fhir_client()

    anonymized_count = 0

    for gdpr in expired_records:
        # Capturer les valeurs avant toute opération async
        gdpr_id = gdpr.id
        fhir_resource_id = gdpr.fhir_resource_id
        soft_deleted_at = gdpr.soft_deleted_at
        deletion_reason = gdpr.deletion_reason

        try:
            logger.info(
                f"Anonymisation du professionnel {gdpr_id} (soft deleted le {soft_deleted_at})"
            )

            # Récupérer et anonymiser la ressource FHIR
            fhir_practitioner = await fhir_client.read("Practitioner", fhir_resource_id)
            _anonymize_fhir_practitioner(fhir_practitioner, gdpr_id)
            await fhir_client.update(fhir_practitioner)

            # Marquer comme anonymisé dans GDPR metadata
            gdpr.anonymized_at = now
            gdpr.updated_at = now

            await db.commit()
            await db.refresh(gdpr)

            # Publier événement anonymized
            await publish(
                "identity.professional.anonymized",
                {
                    "professional_id": gdpr_id,
                    "anonymized_at": now.isoformat(),
                    "soft_deleted_at": (soft_deleted_at.isoformat() if soft_deleted_at else None),
                    "deletion_reason": deletion_reason,
                    "grace_period_days": 7,
                },
            )

            anonymized_count += 1
            logger.info(f"Professionnel {gdpr_id} anonymisé avec succès")

        except Exception as e:
            logger.error(f"Échec anonymisation professionnel {gdpr_id}: {e}", exc_info=True)
            await db.rollback()
            continue

    logger.info(f"Anonymisation terminée: {anonymized_count}/{len(expired_records)} réussies")
    return anonymized_count


def _anonymize_fhir_practitioner(practitioner, gdpr_id: int) -> None:
    """
    Anonymise une ressource FHIR Practitioner.

    Remplace les données PII par des valeurs hashées bcrypt irréversibles.

    Args:
        practitioner: Ressource FHIR Practitioner à anonymiser
        gdpr_id: ID local pour générer les valeurs anonymisées
    """
    from fhir.resources.contactpoint import ContactPoint
    from fhir.resources.humanname import HumanName
    from fhir.resources.identifier import Identifier

    salt = bcrypt.gensalt()

    # Anonymiser le nom
    anonymized_first = bcrypt.hashpw(f"ANONYME_{gdpr_id}".encode(), salt).decode("utf-8")
    anonymized_last = bcrypt.hashpw(f"PROFESSIONAL_{gdpr_id}".encode(), salt).decode("utf-8")
    practitioner.name = [HumanName(family=anonymized_last, given=[anonymized_first], prefix=["Dr"])]

    # Anonymiser les contacts (email, phone)
    anonymized_email = bcrypt.hashpw(f"deleted_{gdpr_id}@anonymized.local".encode(), salt).decode(
        "utf-8"
    )
    anonymized_phone = "+ANONYMIZED"
    practitioner.telecom = [
        ContactPoint(system="email", value=anonymized_email),
        ContactPoint(system="phone", value=anonymized_phone),
    ]

    # Garder les identifiants mais anonymiser le keycloak_user_id
    if practitioner.identifier:
        new_identifiers = []
        for identifier in practitioner.identifier:
            if identifier.system == KEYCLOAK_SYSTEM:
                # Remplacer par un ID anonymisé
                anonymized_keycloak = bcrypt.hashpw(
                    f"keycloak_anon_{gdpr_id}".encode(), salt
                ).decode("utf-8")
                new_identifiers.append(
                    Identifier(system=KEYCLOAK_SYSTEM, value=anonymized_keycloak)
                )
            elif identifier.system == PROFESSIONAL_LICENSE_SYSTEM:
                # Anonymiser aussi le numéro de licence
                anonymized_license = bcrypt.hashpw(f"license_anon_{gdpr_id}".encode(), salt).decode(
                    "utf-8"
                )
                new_identifiers.append(
                    Identifier(system=PROFESSIONAL_LICENSE_SYSTEM, value=anonymized_license)
                )
            else:
                # Garder les autres identifiants
                new_identifiers.append(identifier)
        practitioner.identifier = new_identifiers

    # Supprimer les qualifications (specialty, etc.)
    practitioner.qualification = None

    # Supprimer les communications (langues)
    practitioner.communication = None

    # Supprimer les extensions (facility info, experience)
    practitioner.extension = None

    # Garder active=false
    practitioner.active = False


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
