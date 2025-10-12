"""Schémas Pydantic pour Patient.

Ce module définit les schémas de validation pour les opérations CRUD
sur les patients, avec support du contexte africain.

Note: Ce service gère uniquement l'identité des patients (données démographiques,
contact, localisation). Les données médicales (groupe sanguin, allergies,
historique médical) sont gérées par le service core-africare-ehr.
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.utils import (
    Email,
    Latitude,
    Longitude,
    NationalId,
    NonEmptyStr,
    PatientId,
    PhoneNumber,
)


class PatientBase(BaseModel):
    """Schéma de base partagé pour Patient."""

    # Informations démographiques
    first_name: NonEmptyStr = Field(
        ...,
        description="Prénom du patient",
        examples=["Amadou"]
    )
    last_name: NonEmptyStr = Field(
        ...,
        description="Nom de famille du patient",
        examples=["Diallo"]
    )
    date_of_birth: date = Field(
        ...,
        description="Date de naissance",
        examples=["1990-05-15"]
    )
    gender: Literal["male", "female", "other", "unknown"] = Field(
        ...,
        description="Sexe biologique"
    )

    # Contact
    email: Optional[Email] = Field(
        None,
        description="Adresse email"
    )
    phone: Optional[PhoneNumber] = Field(
        None,
        description="Téléphone principal au format E.164",
        examples=["+221771234567"]
    )
    phone_secondary: Optional[PhoneNumber] = Field(
        None,
        description="Téléphone secondaire (famille, urgence)"
    )

    # Adresse
    address_line1: Optional[str] = Field(
        None,
        max_length=255,
        description="Adresse principale"
    )
    address_line2: Optional[str] = Field(
        None,
        max_length=255,
        description="Complément d'adresse"
    )
    city: Optional[str] = Field(
        None,
        max_length=100,
        description="Ville"
    )
    region: Optional[str] = Field(
        None,
        max_length=100,
        description="Région administrative"
    )
    postal_code: Optional[str] = Field(
        None,
        max_length=20,
        description="Code postal (optionnel)"
    )
    country: str = Field(
        default="Sénégal",
        max_length=100,
        description="Pays de résidence"
    )

    # GPS
    latitude: Optional[Latitude] = Field(
        None,
        description="Latitude GPS pour localisation en zones rurales"
    )
    longitude: Optional[Longitude] = Field(
        None,
        description="Longitude GPS pour localisation en zones rurales"
    )

    # Contact d'urgence
    emergency_contact_name: Optional[str] = Field(
        None,
        max_length=200,
        description="Nom du contact d'urgence"
    )
    emergency_contact_phone: Optional[PhoneNumber] = Field(
        None,
        description="Téléphone du contact d'urgence"
    )

    # Langue préférée
    preferred_language: Literal["fr", "wo", "en"] = Field(
        default="fr",
        description="Langue de communication (fr=Français, wo=Wolof, en=English)"
    )

    # Notes
    notes: Optional[str] = Field(
        None,
        max_length=5000,
        description="Notes administratives (non médicales)"
    )

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: date) -> date:
        """Valide que la date de naissance est cohérente."""
        if v > date.today():
            raise ValueError("La date de naissance ne peut pas être dans le futur")
        if v.year < 1900:
            raise ValueError("La date de naissance doit être après 1900")
        return v


class PatientCreate(PatientBase):
    """Schéma pour créer un nouveau patient."""

    keycloak_user_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="UUID de l'utilisateur dans Keycloak",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"]
    )
    national_id: Optional[NationalId] = Field(
        None,
        description="Numéro d'identification nationale (CNI, passeport)"
    )


class PatientUpdate(BaseModel):
    """Schéma pour mettre à jour un patient existant.

    Tous les champs sont optionnels pour permettre des mises à jour partielles.
    """

    first_name: Optional[NonEmptyStr] = None
    last_name: Optional[NonEmptyStr] = None
    date_of_birth: Optional[date] = None
    gender: Optional[Literal["male", "female", "other", "unknown"]] = None
    email: Optional[Email] = None
    phone: Optional[PhoneNumber] = None
    phone_secondary: Optional[PhoneNumber] = None
    address_line1: Optional[str] = Field(None, max_length=255)
    address_line2: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=100)
    postal_code: Optional[str] = Field(None, max_length=20)
    country: Optional[str] = Field(None, max_length=100)
    latitude: Optional[Latitude] = None
    longitude: Optional[Longitude] = None
    emergency_contact_name: Optional[str] = Field(None, max_length=200)
    emergency_contact_phone: Optional[PhoneNumber] = None
    preferred_language: Optional[Literal["fr", "wo", "en"]] = None
    notes: Optional[str] = Field(None, max_length=5000)
    is_active: Optional[bool] = None

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: Optional[date]) -> Optional[date]:
        """Valide que la date de naissance est cohérente."""
        if v is None:
            return v
        if v > date.today():
            raise ValueError("La date de naissance ne peut pas être dans le futur")
        if v.year < 1900:
            raise ValueError("La date de naissance doit être après 1900")
        return v


class PatientResponse(PatientBase):
    """Schéma de réponse pour un patient."""

    id: PatientId
    keycloak_user_id: str
    national_id: Optional[str]
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    updated_by: Optional[str]

    model_config = {"from_attributes": True}


class PatientListItem(BaseModel):
    """Schéma optimisé pour liste de patients (champs essentiels uniquement)."""

    id: PatientId
    first_name: str
    last_name: str
    date_of_birth: date
    gender: Literal["male", "female", "other", "unknown"]
    phone: Optional[str]
    email: Optional[str]
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PatientSearchFilters(BaseModel):
    """Filtres de recherche pour patients."""

    first_name: Optional[str] = Field(
        None,
        description="Recherche par prénom (partielle, insensible à la casse)"
    )
    last_name: Optional[str] = Field(
        None,
        description="Recherche par nom (partielle, insensible à la casse)"
    )
    national_id: Optional[str] = Field(
        None,
        description="Recherche exacte par ID national"
    )
    email: Optional[str] = Field(
        None,
        description="Recherche exacte par email"
    )
    phone: Optional[str] = Field(
        None,
        description="Recherche exacte par téléphone"
    )
    gender: Optional[Literal["male", "female", "other", "unknown"]] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    region: Optional[str] = Field(
        None,
        description="Filtrer par région administrative"
    )
    city: Optional[str] = Field(
        None,
        description="Filtrer par ville"
    )

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


class PatientListResponse(BaseModel):
    """Réponse paginée pour liste de patients."""

    items: list[PatientListItem] = Field(
        ...,
        description="Liste des patients"
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
