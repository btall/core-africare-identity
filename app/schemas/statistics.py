"""Schémas Pydantic pour les statistiques du dashboard.

Ce module définit les schémas de réponse pour les endpoints de statistiques
utilisés par le portal d'administration.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class PatientStatistics(BaseModel):
    """Statistiques détaillées des patients."""

    total_patients: int = Field(..., description="Nombre total de patients")
    active_patients: int = Field(..., description="Nombre de patients actifs")
    inactive_patients: int = Field(..., description="Nombre de patients inactifs")
    verified_patients: int = Field(..., description="Nombre de patients vérifiés")
    unverified_patients: int = Field(..., description="Nombre de patients non vérifiés")
    patients_by_gender: dict[str, int] = Field(
        default_factory=dict, description="Répartition par sexe (male/female)"
    )
    patients_by_region: dict[str, int] = Field(
        default_factory=dict, description="Répartition par région"
    )


class ProfessionalStatistics(BaseModel):
    """Statistiques détaillées des professionnels de santé."""

    total_professionals: int = Field(..., description="Nombre total de professionnels")
    active_professionals: int = Field(..., description="Nombre de professionnels actifs")
    inactive_professionals: int = Field(..., description="Nombre de professionnels inactifs")
    verified_professionals: int = Field(..., description="Nombre de professionnels vérifiés")
    unverified_professionals: int = Field(..., description="Nombre de professionnels non vérifiés")
    available_professionals: int = Field(
        ..., description="Nombre de professionnels disponibles pour consultations"
    )
    professionals_by_type: dict[str, int] = Field(
        default_factory=dict,
        description="Répartition par type (physician, nurse, midwife, pharmacist, technician, other)",
    )
    professionals_by_specialty: dict[str, int] = Field(
        default_factory=dict, description="Répartition par spécialité"
    )


class DashboardStatistics(BaseModel):
    """Statistiques globales pour le dashboard administrateur."""

    # Statistiques patients
    total_patients: int = Field(..., description="Nombre total de patients")
    active_patients: int = Field(..., description="Nombre de patients actifs")
    inactive_patients: int = Field(..., description="Nombre de patients inactifs")

    # Statistiques professionnels
    total_professionals: int = Field(..., description="Nombre total de professionnels")
    active_professionals: int = Field(..., description="Nombre de professionnels actifs")
    inactive_professionals: int = Field(..., description="Nombre de professionnels inactifs")

    # Métadonnées
    last_updated: datetime = Field(..., description="Date de dernière mise à jour des statistiques")
