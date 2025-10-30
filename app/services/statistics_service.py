"""Service métier pour les statistiques du dashboard.

Ce module implémente la logique métier pour l'agrégation et le calcul
des statistiques sur les patients et professionnels de santé.
"""

from datetime import UTC, datetime

from opentelemetry import trace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient
from app.models.professional import Professional
from app.schemas.statistics import (
    DashboardStatistics,
    PatientStatistics,
    ProfessionalStatistics,
)

tracer = trace.get_tracer(__name__)


async def get_patient_statistics(db: AsyncSession) -> PatientStatistics:
    """
    Calcule les statistiques détaillées des patients.

    Args:
        db: Session de base de données async

    Returns:
        Statistiques complètes des patients
    """
    with tracer.start_as_current_span("get_patient_statistics"):
        # Statistiques de base
        total_result = await db.execute(
            select(func.count(Patient.id)).where(Patient.deleted_at.is_(None))
        )
        total_patients = total_result.scalar_one()

        active_result = await db.execute(
            select(func.count(Patient.id)).where(
                Patient.deleted_at.is_(None), Patient.is_active.is_(True)
            )
        )
        active_patients = active_result.scalar_one()

        verified_result = await db.execute(
            select(func.count(Patient.id)).where(
                Patient.deleted_at.is_(None), Patient.is_verified.is_(True)
            )
        )
        verified_patients = verified_result.scalar_one()

        # Répartition par sexe
        gender_result = await db.execute(
            select(Patient.gender, func.count(Patient.id))
            .where(Patient.deleted_at.is_(None))
            .group_by(Patient.gender)
        )
        patients_by_gender = {row[0]: row[1] for row in gender_result.all()}

        # Répartition par région
        region_result = await db.execute(
            select(Patient.region, func.count(Patient.id))
            .where(Patient.deleted_at.is_(None), Patient.region.is_not(None))
            .group_by(Patient.region)
        )
        patients_by_region = {row[0]: row[1] for row in region_result.all()}

        return PatientStatistics(
            total_patients=total_patients,
            active_patients=active_patients,
            inactive_patients=total_patients - active_patients,
            verified_patients=verified_patients,
            unverified_patients=total_patients - verified_patients,
            patients_by_gender=patients_by_gender,
            patients_by_region=patients_by_region,
        )


async def get_professional_statistics(db: AsyncSession) -> ProfessionalStatistics:
    """
    Calcule les statistiques détaillées des professionnels de santé.

    Args:
        db: Session de base de données async

    Returns:
        Statistiques complètes des professionnels
    """
    with tracer.start_as_current_span("get_professional_statistics"):
        # Statistiques de base
        total_result = await db.execute(
            select(func.count(Professional.id)).where(Professional.deleted_at.is_(None))
        )
        total_professionals = total_result.scalar_one()

        active_result = await db.execute(
            select(func.count(Professional.id)).where(
                Professional.deleted_at.is_(None), Professional.is_active.is_(True)
            )
        )
        active_professionals = active_result.scalar_one()

        verified_result = await db.execute(
            select(func.count(Professional.id)).where(
                Professional.deleted_at.is_(None), Professional.is_verified.is_(True)
            )
        )
        verified_professionals = verified_result.scalar_one()

        available_result = await db.execute(
            select(func.count(Professional.id)).where(
                Professional.deleted_at.is_(None), Professional.is_available.is_(True)
            )
        )
        available_professionals = available_result.scalar_one()

        # Répartition par type
        type_result = await db.execute(
            select(Professional.professional_type, func.count(Professional.id))
            .where(Professional.deleted_at.is_(None))
            .group_by(Professional.professional_type)
        )
        professionals_by_type = {row[0]: row[1] for row in type_result.all()}

        # Répartition par spécialité
        specialty_result = await db.execute(
            select(Professional.specialty, func.count(Professional.id))
            .where(Professional.deleted_at.is_(None), Professional.specialty.is_not(None))
            .group_by(Professional.specialty)
        )
        professionals_by_specialty = {row[0]: row[1] for row in specialty_result.all()}

        return ProfessionalStatistics(
            total_professionals=total_professionals,
            active_professionals=active_professionals,
            inactive_professionals=total_professionals - active_professionals,
            verified_professionals=verified_professionals,
            unverified_professionals=total_professionals - verified_professionals,
            available_professionals=available_professionals,
            professionals_by_type=professionals_by_type,
            professionals_by_specialty=professionals_by_specialty,
        )


async def get_dashboard_statistics(db: AsyncSession) -> DashboardStatistics:
    """
    Calcule les statistiques globales du dashboard administrateur.

    Cette fonction agrège uniquement les métriques principales nécessaires
    pour l'affichage rapide du dashboard.

    Args:
        db: Session de base de données async

    Returns:
        Statistiques globales du dashboard
    """
    with tracer.start_as_current_span("get_dashboard_statistics"):
        # Statistiques patients
        total_patients_result = await db.execute(
            select(func.count(Patient.id)).where(Patient.deleted_at.is_(None))
        )
        total_patients = total_patients_result.scalar_one()

        active_patients_result = await db.execute(
            select(func.count(Patient.id)).where(
                Patient.deleted_at.is_(None), Patient.is_active.is_(True)
            )
        )
        active_patients = active_patients_result.scalar_one()

        # Statistiques professionnels
        total_professionals_result = await db.execute(
            select(func.count(Professional.id)).where(Professional.deleted_at.is_(None))
        )
        total_professionals = total_professionals_result.scalar_one()

        active_professionals_result = await db.execute(
            select(func.count(Professional.id)).where(
                Professional.deleted_at.is_(None), Professional.is_active.is_(True)
            )
        )
        active_professionals = active_professionals_result.scalar_one()

        return DashboardStatistics(
            total_patients=total_patients,
            active_patients=active_patients,
            inactive_patients=total_patients - active_patients,
            total_professionals=total_professionals,
            active_professionals=active_professionals,
            inactive_professionals=total_professionals - active_professionals,
            last_updated=datetime.now(UTC),
        )
