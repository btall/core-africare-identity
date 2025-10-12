"""Schémas Pydantic pour Professional.

Ce module définit les schémas de validation pour les opérations CRUD
sur les professionnels de santé.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.utils import (
    Email,
    NonEmptyStr,
    PhoneNumber,
    ProfessionalId,
)


class ProfessionalBase(BaseModel):
    """Schéma de base partagé pour Professional."""

    # Informations personnelles
    first_name: NonEmptyStr = Field(
        ...,
        description="Prénom du professionnel",
        examples=["Fatou"]
    )
    last_name: NonEmptyStr = Field(
        ...,
        description="Nom de famille du professionnel",
        examples=["Sall"]
    )
    title: Literal["Dr", "Pr", "Inf", "Sage-femme", "Pharmacien", "Autre"] = Field(
        default="Dr",
        description="Titre professionnel"
    )

    # Informations professionnelles
    specialty: NonEmptyStr = Field(
        ...,
        description="Spécialité médicale principale",
        examples=["Médecine Générale", "Pédiatrie", "Gynécologie"]
    )
    sub_specialty: Optional[str] = Field(
        None,
        max_length=100,
        description="Sous-spécialité médicale"
    )
    professional_type: Literal[
        "physician", "nurse", "midwife", "pharmacist", "technician", "other"
    ] = Field(
        ...,
        description="Type de professionnel de santé"
    )

    # Contact professionnel
    email: Email = Field(
        ...,
        description="Adresse email professionnelle"
    )
    phone: PhoneNumber = Field(
        ...,
        description="Téléphone professionnel au format E.164",
        examples=["+221771234567"]
    )
    phone_secondary: Optional[PhoneNumber] = Field(
        None,
        description="Téléphone secondaire"
    )

    # Établissement
    facility_name: Optional[str] = Field(
        None,
        max_length=255,
        description="Nom de l'établissement de santé"
    )
    facility_type: Optional[
        Literal["hospital", "clinic", "health_post", "private_practice", "other"]
    ] = Field(
        None,
        description="Type d'établissement"
    )
    facility_address: Optional[str] = Field(
        None,
        max_length=500,
        description="Adresse de l'établissement"
    )
    facility_city: Optional[str] = Field(
        None,
        max_length=100,
        description="Ville de l'établissement"
    )
    facility_region: Optional[str] = Field(
        None,
        max_length=100,
        description="Région de l'établissement"
    )

    # Qualifications
    qualifications: Optional[str] = Field(
        None,
        max_length=5000,
        description="Diplômes et qualifications (JSON ou texte libre)"
    )
    years_of_experience: Optional[int] = Field(
        None,
        ge=0,
        le=70,
        description="Années d'expérience professionnelle"
    )

    # Langues parlées
    languages_spoken: str = Field(
        default="fr",
        max_length=100,
        description="Langues parlées (codes séparés par virgule: fr,en)",
        examples=["fr", "fr,en"]
    )

    # Disponibilité
    is_available: bool = Field(
        default=True,
        description="Disponible pour consultations"
    )

    # Notes
    notes: Optional[str] = Field(
        None,
        max_length=5000,
        description="Notes administratives"
    )

    @field_validator("years_of_experience")
    @classmethod
    def validate_experience(cls, v: Optional[int]) -> Optional[int]:
        """Valide que l'expérience est cohérente."""
        if v is not None and v < 0:
            raise ValueError("L'expérience ne peut pas être négative")
        if v is not None and v > 70:
            raise ValueError("L'expérience semble excessive (max 70 ans)")
        return v


class ProfessionalCreate(ProfessionalBase):
    """Schéma pour créer un nouveau professionnel."""

    keycloak_user_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="UUID de l'utilisateur dans Keycloak",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"]
    )
    professional_id: Optional[str] = Field(
        None,
        min_length=5,
        max_length=50,
        description="Numéro d'ordre professionnel (CNOM, etc.)"
    )


class ProfessionalUpdate(BaseModel):
    """Schéma pour mettre à jour un professionnel existant.

    Tous les champs sont optionnels pour permettre des mises à jour partielles.
    """

    first_name: Optional[NonEmptyStr] = None
    last_name: Optional[NonEmptyStr] = None
    title: Optional[Literal["Dr", "Pr", "Inf", "Sage-femme", "Pharmacien", "Autre"]] = None
    specialty: Optional[NonEmptyStr] = None
    sub_specialty: Optional[str] = Field(None, max_length=100)
    professional_type: Optional[
        Literal["physician", "nurse", "midwife", "pharmacist", "technician", "other"]
    ] = None
    email: Optional[Email] = None
    phone: Optional[PhoneNumber] = None
    phone_secondary: Optional[PhoneNumber] = None
    facility_name: Optional[str] = Field(None, max_length=255)
    facility_type: Optional[
        Literal["hospital", "clinic", "health_post", "private_practice", "other"]
    ] = None
    facility_address: Optional[str] = Field(None, max_length=500)
    facility_city: Optional[str] = Field(None, max_length=100)
    facility_region: Optional[str] = Field(None, max_length=100)
    qualifications: Optional[str] = Field(None, max_length=5000)
    years_of_experience: Optional[int] = Field(None, ge=0, le=70)
    languages_spoken: Optional[str] = Field(None, max_length=100)
    is_available: Optional[bool] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=5000)

    @field_validator("years_of_experience")
    @classmethod
    def validate_experience(cls, v: Optional[int]) -> Optional[int]:
        """Valide que l'expérience est cohérente."""
        if v is not None and v < 0:
            raise ValueError("L'expérience ne peut pas être négative")
        if v is not None and v > 70:
            raise ValueError("L'expérience semble excessive (max 70 ans)")
        return v


class ProfessionalResponse(ProfessionalBase):
    """Schéma de réponse pour un professionnel."""

    id: ProfessionalId
    keycloak_user_id: str
    professional_id: Optional[str]
    is_active: bool
    is_verified: bool
    digital_signature: Optional[str]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    updated_by: Optional[str]

    model_config = {"from_attributes": True}


class ProfessionalListItem(BaseModel):
    """Schéma optimisé pour liste de professionnels (champs essentiels uniquement)."""

    id: ProfessionalId
    title: str
    first_name: str
    last_name: str
    specialty: str
    professional_type: str
    email: str
    phone: str
    facility_name: Optional[str]
    is_active: bool
    is_verified: bool
    is_available: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ProfessionalSearchFilters(BaseModel):
    """Filtres de recherche pour professionnels."""

    first_name: Optional[str] = Field(
        None,
        description="Recherche par prénom (partielle, insensible à la casse)"
    )
    last_name: Optional[str] = Field(
        None,
        description="Recherche par nom (partielle, insensible à la casse)"
    )
    professional_id: Optional[str] = Field(
        None,
        description="Recherche exacte par numéro d'ordre"
    )
    specialty: Optional[str] = Field(
        None,
        description="Filtrer par spécialité"
    )
    professional_type: Optional[
        Literal["physician", "nurse", "midwife", "pharmacist", "technician", "other"]
    ] = Field(
        None,
        description="Filtrer par type de professionnel"
    )
    facility_name: Optional[str] = Field(
        None,
        description="Recherche par établissement (partielle)"
    )
    facility_city: Optional[str] = Field(
        None,
        description="Filtrer par ville de l'établissement"
    )
    facility_region: Optional[str] = Field(
        None,
        description="Filtrer par région de l'établissement"
    )
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    is_available: Optional[bool] = None

    # Pagination
    skip: int = Field(
        default=0,
        ge=0,
        description="Nombre d'éléments à sauter"
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Nombre maximum d'éléments à retourner"
    )


class ProfessionalListResponse(BaseModel):
    """Réponse paginée pour liste de professionnels."""

    items: list[ProfessionalListItem] = Field(
        ...,
        description="Liste des professionnels"
    )
    total: int = Field(
        ...,
        ge=0,
        description="Nombre total de résultats"
    )
    skip: int = Field(
        ...,
        ge=0,
        description="Nombre d'éléments sautés"
    )
    limit: int = Field(
        ...,
        ge=1,
        description="Limite par page"
    )
