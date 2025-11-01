"""Endpoints API pour les statistiques du dashboard.

Ce module définit tous les endpoints REST pour récupérer les statistiques
des patients et professionnels de santé pour le dashboard administrateur.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import User, get_current_user, require_roles
from app.schemas.statistics import (
    DashboardStatistics,
    PatientStatistics,
    ProfessionalStatistics,
)
from app.services import statistics_service

router = APIRouter()


@router.get(
    "/dashboard",
    response_model=DashboardStatistics,
    status_code=status.HTTP_200_OK,
    summary="Statistiques globales du dashboard",
    description="Récupère les statistiques principales pour le dashboard administrateur",
    dependencies=[Depends(require_roles("admin"))],
)
async def get_dashboard_statistics(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DashboardStatistics:
    """
    Récupère les statistiques globales du dashboard.

    Cette endpoint agrège les métriques principales:
    - Total patients (actifs/inactifs)
    - Total professionnels (actifs/inactifs)
    - Horodatage de dernière mise à jour

    Permissions requises : role 'admin'
    """
    return await statistics_service.get_dashboard_statistics(db)


@router.get(
    "/patients",
    response_model=PatientStatistics,
    status_code=status.HTTP_200_OK,
    summary="Statistiques détaillées des patients",
    description="Récupère les statistiques complètes des patients avec répartitions par genre et région",
    dependencies=[Depends(require_roles("admin"))],
)
async def get_patient_statistics(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> PatientStatistics:
    """
    Récupère les statistiques détaillées des patients.

    Cette endpoint fournit:
    - Total patients (actifs/inactifs/vérifiés)
    - Répartition par sexe (male/female)
    - Répartition par région

    Permissions requises : role 'admin'
    """
    return await statistics_service.get_patient_statistics(db)


@router.get(
    "/professionals",
    response_model=ProfessionalStatistics,
    status_code=status.HTTP_200_OK,
    summary="Statistiques détaillées des professionnels",
    description="Récupère les statistiques complètes des professionnels avec répartitions par type et spécialité",
    dependencies=[Depends(require_roles("admin"))],
)
async def get_professional_statistics(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProfessionalStatistics:
    """
    Récupère les statistiques détaillées des professionnels de santé.

    Cette endpoint fournit:
    - Total professionnels (actifs/inactifs/vérifiés/disponibles)
    - Répartition par type (physician, nurse, midwife, pharmacist, technician, other)
    - Répartition par spécialité

    Permissions requises : role 'admin'
    """
    return await statistics_service.get_professional_statistics(db)
