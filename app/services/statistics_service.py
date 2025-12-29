"""Service métier pour les statistiques du dashboard.

Ce module implémente la logique métier pour l'agrégation et le calcul
des statistiques sur les patients et professionnels de santé.

Architecture hybride FHIR + PostgreSQL:
- Comptages GDPR (verified, available, deleted): PostgreSQL (GDPR metadata)
- Comptages démographiques (gender, region, specialty): FHIR search
- Active status: FHIR (Patient/Practitioner.active field)
"""

import logging
from datetime import UTC, datetime

from opentelemetry import trace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get, cache_key_stats_dashboard, cache_set
from app.core.config import settings
from app.infrastructure.fhir.client import get_fhir_client
from app.models.gdpr_metadata import PatientGdprMetadata, ProfessionalGdprMetadata
from app.schemas.statistics import (
    DashboardStatistics,
    PatientStatistics,
    ProfessionalStatistics,
)

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


async def _get_fhir_count(resource_type: str, params: dict[str, str] | None = None) -> int:
    """
    Récupère le nombre de ressources FHIR via search avec _summary=count.

    Args:
        resource_type: Type de ressource ("Patient" ou "Practitioner")
        params: Paramètres de recherche FHIR

    Returns:
        Nombre de ressources trouvées, 0 en cas d'erreur
    """
    try:
        fhir_client = get_fhir_client()
        search_params = params.copy() if params else {}
        search_params["_summary"] = "count"
        bundle = await fhir_client.search(resource_type, search_params)
        return bundle.total or 0
    except Exception as e:
        logger.warning(f"FHIR count query failed for {resource_type}: {e}")
        return 0


async def get_patient_statistics(db: AsyncSession) -> PatientStatistics:
    """
    Calcule les statistiques détaillées des patients.

    Architecture hybride:
    - total_patients, active_patients: FHIR search
    - verified_patients: GDPR metadata
    - patients_by_gender, patients_by_region: FHIR search

    Args:
        db: Session de base de données async

    Returns:
        Statistiques complètes des patients
    """
    with tracer.start_as_current_span("get_patient_statistics"):
        # Total patients actifs (non supprimés) via FHIR
        total_patients = await _get_fhir_count("Patient", {"active": "true"})

        # Fallback: Si FHIR count échoue, utiliser GDPR metadata count
        if total_patients == 0:
            result = await db.execute(
                select(func.count(PatientGdprMetadata.id)).where(
                    PatientGdprMetadata.soft_deleted_at.is_(None),
                    PatientGdprMetadata.anonymized_at.is_(None),
                )
            )
            total_patients = result.scalar_one()

        # Patients vérifiés (local GDPR)
        verified_result = await db.execute(
            select(func.count(PatientGdprMetadata.id)).where(
                PatientGdprMetadata.soft_deleted_at.is_(None),
                PatientGdprMetadata.anonymized_at.is_(None),
                PatientGdprMetadata.is_verified.is_(True),
            )
        )
        verified_patients = verified_result.scalar_one()

        # Répartition par sexe (FHIR)
        patients_by_gender: dict[str, int] = {}
        for gender in ["male", "female", "other", "unknown"]:
            count = await _get_fhir_count("Patient", {"gender": gender, "active": "true"})
            if count > 0:
                patients_by_gender[gender] = count

        # Répartition par région (FHIR - address-state)
        # Note: Nécessite que les patients aient une adresse avec state/region
        patients_by_region: dict[str, int] = {}
        # Pour l'instant, on ne peut pas faire de GROUP BY en FHIR
        # Cette fonctionnalité nécessiterait des requêtes multiples par région connue
        # ou une table de cache/matérialisée

        # Active patients = total (tous sont active=true dans la query)
        active_patients = total_patients

        return PatientStatistics(
            total_patients=total_patients,
            active_patients=active_patients,
            inactive_patients=0,  # Les inactifs sont exclus de la query FHIR
            verified_patients=verified_patients,
            unverified_patients=total_patients - verified_patients,
            patients_by_gender=patients_by_gender,
            patients_by_region=patients_by_region,
        )


async def get_professional_statistics(db: AsyncSession) -> ProfessionalStatistics:
    """
    Calcule les statistiques détaillées des professionnels de santé.

    Architecture hybride:
    - total_professionals, active_professionals: FHIR search
    - verified_professionals, available_professionals: GDPR metadata
    - professionals_by_type, professionals_by_specialty: FHIR search (limité)

    Args:
        db: Session de base de données async

    Returns:
        Statistiques complètes des professionnels
    """
    with tracer.start_as_current_span("get_professional_statistics"):
        # Total professionnels actifs via FHIR
        total_professionals = await _get_fhir_count("Practitioner", {"active": "true"})

        # Fallback: Si FHIR count échoue, utiliser GDPR metadata count
        if total_professionals == 0:
            result = await db.execute(
                select(func.count(ProfessionalGdprMetadata.id)).where(
                    ProfessionalGdprMetadata.soft_deleted_at.is_(None),
                    ProfessionalGdprMetadata.anonymized_at.is_(None),
                )
            )
            total_professionals = result.scalar_one()

        # Professionnels vérifiés (local GDPR)
        verified_result = await db.execute(
            select(func.count(ProfessionalGdprMetadata.id)).where(
                ProfessionalGdprMetadata.soft_deleted_at.is_(None),
                ProfessionalGdprMetadata.anonymized_at.is_(None),
                ProfessionalGdprMetadata.is_verified.is_(True),
            )
        )
        verified_professionals = verified_result.scalar_one()

        # Professionnels disponibles (local GDPR)
        available_result = await db.execute(
            select(func.count(ProfessionalGdprMetadata.id)).where(
                ProfessionalGdprMetadata.soft_deleted_at.is_(None),
                ProfessionalGdprMetadata.anonymized_at.is_(None),
                ProfessionalGdprMetadata.is_available.is_(True),
            )
        )
        available_professionals = available_result.scalar_one()

        # Répartition par type et spécialité
        # Note: Ces données sont dans FHIR qualification[], pas facilement queryable
        # Pour MVP, on retourne des dicts vides - à implémenter avec cache si besoin
        professionals_by_type: dict[str, int] = {}
        professionals_by_specialty: dict[str, int] = {}

        # Active = total (query FHIR avec active=true)
        active_professionals = total_professionals

        return ProfessionalStatistics(
            total_professionals=total_professionals,
            active_professionals=active_professionals,
            inactive_professionals=0,  # Exclus de la query FHIR
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

    Architecture hybride (avec cache):
    1. Verifier cache Redis
    2. Si miss: Comptages totaux via FHIR search avec _summary=count
    3. Fallback: GDPR metadata counts
    4. Mettre en cache

    Args:
        db: Session de base de données async

    Returns:
        Statistiques globales du dashboard
    """
    with tracer.start_as_current_span("get_dashboard_statistics") as span:
        # 1. Verifier cache Redis
        cache_key = cache_key_stats_dashboard()
        cached_json = await cache_get(cache_key)
        if cached_json:
            span.add_event("Cache HIT")
            return DashboardStatistics.model_validate_json(cached_json)

        # 2. Cache MISS - Calculer statistiques
        # Statistiques patients via FHIR
        total_patients = await _get_fhir_count("Patient", {"active": "true"})
        active_patients = total_patients  # Query avec active=true

        # Fallback si FHIR échoue
        if total_patients == 0:
            result = await db.execute(
                select(func.count(PatientGdprMetadata.id)).where(
                    PatientGdprMetadata.soft_deleted_at.is_(None),
                    PatientGdprMetadata.anonymized_at.is_(None),
                )
            )
            total_patients = result.scalar_one()
            active_patients = total_patients

        # Statistiques professionnels via FHIR
        total_professionals = await _get_fhir_count("Practitioner", {"active": "true"})
        active_professionals = total_professionals

        # Fallback si FHIR échoue
        if total_professionals == 0:
            result = await db.execute(
                select(func.count(ProfessionalGdprMetadata.id)).where(
                    ProfessionalGdprMetadata.soft_deleted_at.is_(None),
                    ProfessionalGdprMetadata.anonymized_at.is_(None),
                )
            )
            total_professionals = result.scalar_one()
            active_professionals = total_professionals

        response = DashboardStatistics(
            total_patients=total_patients,
            active_patients=active_patients,
            inactive_patients=0,
            total_professionals=total_professionals,
            active_professionals=active_professionals,
            inactive_professionals=0,
            last_updated=datetime.now(UTC),
        )

        # 3. Mettre en cache
        await cache_set(
            cache_key, response.model_dump_json(), ttl=settings.CACHE_TTL_STATS_DASHBOARD
        )

        return response
