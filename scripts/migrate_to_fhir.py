#!/usr/bin/env python3
"""Script de migration des données Patient et Professional vers HAPI FHIR.

Ce script migre les données existantes des tables PostgreSQL vers l'architecture
hybride FHIR + GDPR metadata:

1. Lit les patients/professionals depuis les anciennes tables
2. Crée les ressources FHIR correspondantes dans HAPI FHIR
3. Crée les enregistrements GDPR metadata avec le MEME ID pour rétrocompatibilité
4. Journalise la migration pour audit

Usage:
    # Mode dry-run (aucune modification)
    python scripts/migrate_to_fhir.py --dry-run

    # Migration réelle
    python scripts/migrate_to_fhir.py

    # Migration avec limite (pour tests)
    python scripts/migrate_to_fhir.py --limit 10

    # Forcer la migration (ignorer les erreurs individuelles)
    python scripts/migrate_to_fhir.py --force

Prérequis:
    - HAPI FHIR server accessible
    - PostgreSQL avec anciennes tables patients/professionals
    - Variables d'environnement configurées (SQLALCHEMY_DATABASE_URI, HAPI_FHIR_BASE_URL)
"""

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ajouter le répertoire parent au path pour imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.infrastructure.fhir.client import FHIRClient
from app.infrastructure.fhir.mappers.patient_mapper import PatientMapper
from app.infrastructure.fhir.mappers.professional_mapper import ProfessionalMapper
from app.models.gdpr_metadata import PatientGdprMetadata, ProfessionalGdprMetadata
from app.models.patient import Patient
from app.models.professional import Professional
from app.schemas.patient import PatientCreate
from app.schemas.professional import ProfessionalCreate

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
    ],
)
logger = logging.getLogger(__name__)


class MigrationStats:
    """Statistiques de migration."""

    def __init__(self):
        self.patients_total = 0
        self.patients_migrated = 0
        self.patients_skipped = 0
        self.patients_errors = 0
        self.professionals_total = 0
        self.professionals_migrated = 0
        self.professionals_skipped = 0
        self.professionals_errors = 0
        self.start_time = datetime.now(UTC)
        self.end_time: datetime | None = None

    def summary(self) -> str:
        """Retourne un résumé des statistiques."""
        self.end_time = datetime.now(UTC)
        duration = self.end_time - self.start_time
        return f"""
========================================
        RÉSUMÉ DE MIGRATION
========================================

Patients:
  - Total:    {self.patients_total}
  - Migrés:   {self.patients_migrated}
  - Ignorés:  {self.patients_skipped}
  - Erreurs:  {self.patients_errors}

Professionals:
  - Total:    {self.professionals_total}
  - Migrés:   {self.professionals_migrated}
  - Ignorés:  {self.professionals_skipped}
  - Erreurs:  {self.professionals_errors}

Durée: {duration.total_seconds():.2f} secondes
========================================
"""


def patient_to_create_schema(patient: Patient) -> PatientCreate:
    """Convertit un ancien Patient SQLAlchemy en PatientCreate schema."""
    return PatientCreate(
        keycloak_user_id=patient.keycloak_user_id,
        national_id=patient.national_id,
        first_name=patient.first_name,
        last_name=patient.last_name,
        date_of_birth=patient.date_of_birth,
        gender=patient.gender,
        email=patient.email,
        phone=patient.phone,
        phone_secondary=patient.phone_secondary,
        address_line1=patient.address_line1,
        address_line2=patient.address_line2,
        city=patient.city,
        region=patient.region,
        postal_code=patient.postal_code,
        country=patient.country,
        latitude=patient.latitude,
        longitude=patient.longitude,
        emergency_contact_name=patient.emergency_contact_name,
        emergency_contact_phone=patient.emergency_contact_phone,
        preferred_language=patient.preferred_language,
        notes=patient.notes,
    )


def professional_to_create_schema(professional: Professional) -> ProfessionalCreate:
    """Convertit un ancien Professional SQLAlchemy en ProfessionalCreate schema."""
    return ProfessionalCreate(
        keycloak_user_id=professional.keycloak_user_id,
        professional_id=professional.professional_id,
        first_name=professional.first_name,
        last_name=professional.last_name,
        title=professional.title,
        specialty=professional.specialty,
        sub_specialty=professional.sub_specialty,
        professional_type=professional.professional_type,
        email=professional.email,
        phone=professional.phone,
        phone_secondary=professional.phone_secondary,
        facility_name=professional.facility_name,
        facility_type=professional.facility_type,
        facility_address=professional.facility_address,
        facility_city=professional.facility_city,
        facility_region=professional.facility_region,
        qualifications=professional.qualifications,
        years_of_experience=professional.years_of_experience,
        languages_spoken=professional.languages_spoken,
        is_available=professional.is_available,
        notes=professional.notes,
    )


def patient_to_gdpr_metadata(patient: Patient, fhir_resource_id: str) -> dict[str, Any]:
    """Extrait les champs GDPR d'un Patient pour la nouvelle table."""
    return {
        "id": patient.id,  # MEME ID pour rétrocompatibilité
        "fhir_resource_id": fhir_resource_id,
        "keycloak_user_id": patient.keycloak_user_id,
        "is_verified": patient.is_verified,
        "notes": patient.notes,
        "under_investigation": patient.under_investigation,
        "investigation_notes": patient.investigation_notes,
        "correlation_hash": patient.correlation_hash,
        "soft_deleted_at": patient.soft_deleted_at,
        "anonymized_at": patient.anonymized_at,
        "deleted_by": patient.deleted_by,
        "deletion_reason": patient.deletion_reason,
        "created_at": patient.created_at,
        "updated_at": patient.updated_at,
        "created_by": patient.created_by,
        "updated_by": patient.updated_by,
    }


def professional_to_gdpr_metadata(
    professional: Professional, fhir_resource_id: str
) -> dict[str, Any]:
    """Extrait les champs GDPR d'un Professional pour la nouvelle table."""
    return {
        "id": professional.id,  # MEME ID pour rétrocompatibilité
        "fhir_resource_id": fhir_resource_id,
        "keycloak_user_id": professional.keycloak_user_id,
        "is_verified": professional.is_verified,
        "is_available": professional.is_available,
        "notes": professional.notes,
        "digital_signature": professional.digital_signature,
        "under_investigation": professional.under_investigation,
        "investigation_notes": professional.investigation_notes,
        "correlation_hash": professional.correlation_hash,
        "soft_deleted_at": professional.soft_deleted_at,
        "anonymized_at": professional.anonymized_at,
        "deleted_by": professional.deleted_by,
        "deletion_reason": professional.deletion_reason,
        "created_at": professional.created_at,
        "updated_at": professional.updated_at,
        "created_by": professional.created_by,
        "updated_by": professional.updated_by,
    }


async def check_existing_gdpr_metadata(
    db: AsyncSession, patient_id: int | None = None, professional_id: int | None = None
) -> bool:
    """Vérifie si une entrée GDPR metadata existe déjà."""
    if patient_id is not None:
        result = await db.execute(
            select(PatientGdprMetadata).where(PatientGdprMetadata.id == patient_id)
        )
        return result.scalar_one_or_none() is not None

    if professional_id is not None:
        result = await db.execute(
            select(ProfessionalGdprMetadata).where(ProfessionalGdprMetadata.id == professional_id)
        )
        return result.scalar_one_or_none() is not None

    return False


async def migrate_patient(
    patient: Patient,
    fhir_client: FHIRClient,
    db: AsyncSession,
    dry_run: bool,
    force: bool,
) -> bool:
    """Migre un patient vers FHIR + GDPR metadata.

    Returns:
        True si migré avec succès, False sinon
    """
    patient_id = patient.id  # Capturer avant tout pour éviter lazy loading
    patient_name = f"{patient.first_name} {patient.last_name}"

    try:
        # Vérifier si déjà migré
        if await check_existing_gdpr_metadata(db, patient_id=patient_id):
            logger.info(f"Patient {patient_id} déjà migré, ignoré")
            return False

        # Ignorer les patients déjà anonymisés (données invalides pour FHIR)
        if patient.anonymized_at is not None:
            logger.info(f"Patient {patient_id} déjà anonymisé (anonymized_at set), ignoré")
            return False

        # Ignorer aussi les patients avec email @anonymized.local (données de test)
        if patient.email and "@anonymized.local" in patient.email:
            logger.info(f"Patient {patient_id} a un email anonymisé (@anonymized.local), ignoré")
            return False

        if dry_run:
            logger.info(f"[DRY-RUN] Migrerais patient {patient_id}: {patient_name}")
            return True

        # 1. Convertir en schema et mapper vers FHIR
        patient_create = patient_to_create_schema(patient)
        fhir_patient = PatientMapper.to_fhir(patient_create)

        # 2. Créer dans HAPI FHIR
        created_fhir = await fhir_client.create(fhir_patient)
        fhir_resource_id = created_fhir.id

        logger.info(f"Patient {patient_id} créé dans FHIR avec ID: {fhir_resource_id}")

        # 3. Créer GDPR metadata avec INSERT explicite pour préserver l'ID
        gdpr_data = patient_to_gdpr_metadata(patient, fhir_resource_id)

        # Utiliser INSERT raw pour forcer l'ID
        await db.execute(
            text("""
                INSERT INTO patient_gdpr_metadata (
                    id, fhir_resource_id, keycloak_user_id, is_verified, notes,
                    under_investigation, investigation_notes, correlation_hash,
                    soft_deleted_at, anonymized_at, deleted_by, deletion_reason,
                    created_at, updated_at, created_by, updated_by
                ) VALUES (
                    :id, :fhir_resource_id, :keycloak_user_id, :is_verified, :notes,
                    :under_investigation, :investigation_notes, :correlation_hash,
                    :soft_deleted_at, :anonymized_at, :deleted_by, :deletion_reason,
                    :created_at, :updated_at, :created_by, :updated_by
                )
            """),
            gdpr_data,
        )

        await db.commit()
        logger.info(f"Patient {patient_id} migré avec succès")
        return True

    except Exception as e:
        logger.error(f"Erreur migration patient {patient_id}: {e}")
        await db.rollback()
        if not force:
            raise
        return False


async def migrate_professional(
    professional: Professional,
    fhir_client: FHIRClient,
    db: AsyncSession,
    dry_run: bool,
    force: bool,
) -> bool:
    """Migre un professional vers FHIR + GDPR metadata.

    Returns:
        True si migré avec succès, False sinon
    """
    professional_id = professional.id  # Capturer avant tout pour éviter lazy loading
    professional_name = f"{professional.title} {professional.first_name} {professional.last_name}"

    try:
        # Vérifier si déjà migré
        if await check_existing_gdpr_metadata(db, professional_id=professional_id):
            logger.info(f"Professional {professional_id} déjà migré, ignoré")
            return False

        # Ignorer les professionals déjà anonymisés (données invalides pour FHIR)
        if professional.anonymized_at is not None:
            logger.info(f"Professional {professional_id} déjà anonymisé, ignoré")
            return False

        if dry_run:
            logger.info(f"[DRY-RUN] Migrerais professional {professional_id}: {professional_name}")
            return True

        # 1. Convertir en schema et mapper vers FHIR
        professional_create = professional_to_create_schema(professional)
        fhir_practitioner = ProfessionalMapper.to_fhir(professional_create)

        # 2. Créer dans HAPI FHIR
        created_fhir = await fhir_client.create(fhir_practitioner)
        fhir_resource_id = created_fhir.id

        logger.info(f"Professional {professional_id} créé dans FHIR avec ID: {fhir_resource_id}")

        # 3. Créer GDPR metadata avec INSERT explicite pour préserver l'ID
        gdpr_data = professional_to_gdpr_metadata(professional, fhir_resource_id)

        # Utiliser INSERT raw pour forcer l'ID
        await db.execute(
            text("""
                INSERT INTO professional_gdpr_metadata (
                    id, fhir_resource_id, keycloak_user_id, is_verified, is_available,
                    notes, digital_signature, under_investigation, investigation_notes,
                    correlation_hash, soft_deleted_at, anonymized_at, deleted_by,
                    deletion_reason, created_at, updated_at, created_by, updated_by
                ) VALUES (
                    :id, :fhir_resource_id, :keycloak_user_id, :is_verified, :is_available,
                    :notes, :digital_signature, :under_investigation, :investigation_notes,
                    :correlation_hash, :soft_deleted_at, :anonymized_at, :deleted_by,
                    :deletion_reason, :created_at, :updated_at, :created_by, :updated_by
                )
            """),
            gdpr_data,
        )

        await db.commit()
        logger.info(f"Professional {professional_id} migré avec succès")
        return True

    except Exception as e:
        logger.error(f"Erreur migration professional {professional_id}: {e}")
        await db.rollback()
        if not force:
            raise
        return False


async def migrate_patients(
    fhir_client: FHIRClient,
    db: AsyncSession,
    stats: MigrationStats,
    dry_run: bool,
    force: bool,
    limit: int | None,
):
    """Migre tous les patients."""
    logger.info("=== Migration des Patients ===")

    # Récupérer les patients
    query = select(Patient).order_by(Patient.id)
    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    patients = result.scalars().all()

    stats.patients_total = len(patients)
    logger.info(f"Trouvé {stats.patients_total} patients à migrer")

    for patient in patients:
        patient_id = patient.id  # Capturer avant tout
        try:
            migrated = await migrate_patient(patient, fhir_client, db, dry_run, force)
            if migrated:
                stats.patients_migrated += 1
            else:
                stats.patients_skipped += 1
        except Exception as e:
            stats.patients_errors += 1
            logger.error(f"Patient {patient_id} échoué: {e}")


async def migrate_professionals(
    fhir_client: FHIRClient,
    db: AsyncSession,
    stats: MigrationStats,
    dry_run: bool,
    force: bool,
    limit: int | None,
):
    """Migre tous les professionals."""
    logger.info("=== Migration des Professionals ===")

    # Récupérer les professionals
    query = select(Professional).order_by(Professional.id)
    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    professionals = result.scalars().all()

    stats.professionals_total = len(professionals)
    logger.info(f"Trouvé {stats.professionals_total} professionals à migrer")

    for professional in professionals:
        professional_id = professional.id  # Capturer avant tout
        try:
            migrated = await migrate_professional(professional, fhir_client, db, dry_run, force)
            if migrated:
                stats.professionals_migrated += 1
            else:
                stats.professionals_skipped += 1
        except Exception as e:
            stats.professionals_errors += 1
            logger.error(f"Professional {professional_id} échoué: {e}")


async def update_sequences(db: AsyncSession, dry_run: bool):
    """Met à jour les séquences PostgreSQL pour les nouvelles tables GDPR."""
    logger.info("=== Mise à jour des séquences ===")

    if dry_run:
        logger.info("[DRY-RUN] Mettrais à jour les séquences")
        return

    # Récupérer le max ID des patients migrés
    result = await db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM patient_gdpr_metadata"))
    patient_next_id = result.scalar()

    # Récupérer le max ID des professionals migrés
    result = await db.execute(
        text("SELECT COALESCE(MAX(id), 0) + 1 FROM professional_gdpr_metadata")
    )
    professional_next_id = result.scalar()

    # Mettre à jour les séquences (si elles existent)
    try:
        await db.execute(
            text(f"SELECT setval('patient_gdpr_metadata_id_seq', {patient_next_id}, false)")
        )
        logger.info(f"Séquence patient_gdpr_metadata_id_seq mise à jour: {patient_next_id}")
    except Exception as e:
        logger.warning(f"Impossible de mettre à jour la séquence patient: {e}")

    try:
        await db.execute(
            text(
                f"SELECT setval('professional_gdpr_metadata_id_seq', {professional_next_id}, false)"
            )
        )
        logger.info(
            f"Séquence professional_gdpr_metadata_id_seq mise à jour: {professional_next_id}"
        )
    except Exception as e:
        logger.warning(f"Impossible de mettre à jour la séquence professional: {e}")

    await db.commit()


async def main(dry_run: bool, force: bool, limit: int | None):
    """Point d'entrée principal de la migration."""
    logger.info("=" * 50)
    logger.info("DÉBUT DE LA MIGRATION VERS HAPI FHIR")
    logger.info("=" * 50)
    logger.info(f"Mode dry-run: {dry_run}")
    logger.info(f"Mode force: {force}")
    logger.info(f"Limite: {limit or 'aucune'}")
    logger.info(f"HAPI FHIR URL: {settings.HAPI_FHIR_BASE_URL}")
    logger.info(f"Database: {str(settings.SQLALCHEMY_DATABASE_URI)[:50]}...")

    stats = MigrationStats()

    # Créer le client FHIR
    fhir_client = FHIRClient(
        base_url=str(settings.HAPI_FHIR_BASE_URL),
        timeout=settings.HAPI_FHIR_TIMEOUT,
    )

    # Créer la session de base de données
    engine = create_async_engine(str(settings.SQLALCHEMY_DATABASE_URI), echo=False)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session_maker() as db:
            # Migrer les patients
            await migrate_patients(fhir_client, db, stats, dry_run, force, limit)

            # Migrer les professionals
            await migrate_professionals(fhir_client, db, stats, dry_run, force, limit)

            # Mettre à jour les séquences
            await update_sequences(db, dry_run)

    finally:
        await fhir_client.close()
        await engine.dispose()

    # Afficher le résumé
    logger.info(stats.summary())

    # Code de sortie
    if stats.patients_errors > 0 or stats.professionals_errors > 0:
        logger.error("Migration terminée avec des erreurs")
        return 1

    logger.info("Migration terminée avec succès")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migre les données Patient/Professional vers HAPI FHIR"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule la migration sans modifier les données",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Continue même en cas d'erreurs individuelles",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite le nombre d'enregistrements à migrer (pour tests)",
    )

    args = parser.parse_args()

    exit_code = asyncio.run(main(args.dry_run, args.force, args.limit))
    sys.exit(exit_code)
