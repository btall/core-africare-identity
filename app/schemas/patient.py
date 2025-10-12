"""Schémas Pydantic pour Patient.

Ce module définit les schémas de validation pour les opérations CRUD
sur les patients, avec support du contexte africain.

Note: Ce service gère uniquement l'identité des patients (données démographiques,
contact, localisation). Les données médicales (groupe sanguin, allergies,
historique médical) sont gérées par le service core-africare-ehr.
"""

from datetime import date, datetime
from typing import Literal

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
    first_name: NonEmptyStr = Field(..., description="Prénom du patient", examples=["Amadou"])
    last_name: NonEmptyStr = Field(
        ..., description="Nom de famille du patient", examples=["Diallo"]
    )
    date_of_birth: date = Field(..., description="Date de naissance", examples=["1990-05-15"])
    gender: Literal["male", "female", "other", "unknown"] = Field(
        ..., description="Sexe biologique"
    )

    # Contact
    email: Email | None = Field(None, description="Adresse email")
    phone: PhoneNumber | None = Field(
        None, description="Téléphone principal au format E.164", examples=["+221771234567"]
    )
    phone_secondary: PhoneNumber | None = Field(
        None, description="Téléphone secondaire (famille, urgence)"
    )

    # Adresse
    address_line1: str | None = Field(None, max_length=255, description="Adresse principale")
    address_line2: str | None = Field(None, max_length=255, description="Complément d'adresse")
    city: str | None = Field(None, max_length=100, description="Ville")
    region: str | None = Field(None, max_length=100, description="Région administrative")
    postal_code: str | None = Field(None, max_length=20, description="Code postal (optionnel)")
    country: str = Field(default="Sénégal", max_length=100, description="Pays de résidence")

    # GPS
    latitude: Latitude | None = Field(
        None, description="Latitude GPS pour localisation en zones rurales"
    )
    longitude: Longitude | None = Field(
        None, description="Longitude GPS pour localisation en zones rurales"
    )

    # Contact d'urgence
    emergency_contact_name: str | None = Field(
        None, max_length=200, description="Nom du contact d'urgence"
    )
    emergency_contact_phone: PhoneNumber | None = Field(
        None, description="Téléphone du contact d'urgence"
    )

    # Langue préférée
    preferred_language: Literal["fr", "en"] = Field(
        default="fr", description="Langue de communication (fr=Français, en=English)"
    )

    # Notes
    notes: str | None = Field(
        None, max_length=5000, description="Notes administratives (non médicales)"
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
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )
    national_id: NationalId | None = Field(
        None, description="Numéro d'identification nationale (CNI, passeport)"
    )


class PatientUpdate(BaseModel):
    """Schéma pour mettre à jour un patient existant.

    Tous les champs sont optionnels pour permettre des mises à jour partielles.
    """

    first_name: NonEmptyStr | None = None
    last_name: NonEmptyStr | None = None
    date_of_birth: date | None = None
    gender: Literal["male", "female", "other", "unknown"] | None = None
    email: Email | None = None
    phone: PhoneNumber | None = None
    phone_secondary: PhoneNumber | None = None
    address_line1: str | None = Field(None, max_length=255)
    address_line2: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=100)
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    emergency_contact_name: str | None = Field(None, max_length=200)
    emergency_contact_phone: PhoneNumber | None = None
    preferred_language: Literal["fr", "en"] | None = None
    notes: str | None = Field(None, max_length=5000)
    is_active: bool | None = None

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: date | None) -> date | None:
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
    national_id: str | None
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None

    model_config = {"from_attributes": True}


class PatientListItem(BaseModel):
    """Schéma optimisé pour liste de patients (champs essentiels uniquement)."""

    id: PatientId
    first_name: str
    last_name: str
    date_of_birth: date
    gender: Literal["male", "female", "other", "unknown"]
    phone: str | None
    email: str | None
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PatientSearchFilters(BaseModel):
    """Filtres de recherche pour patients."""

    first_name: str | None = Field(
        None, description="Recherche par prénom (partielle, insensible à la casse)"
    )
    last_name: str | None = Field(
        None, description="Recherche par nom (partielle, insensible à la casse)"
    )
    national_id: str | None = Field(None, description="Recherche exacte par ID national")
    email: str | None = Field(None, description="Recherche exacte par email")
    phone: str | None = Field(None, description="Recherche exacte par téléphone")
    gender: Literal["male", "female", "other", "unknown"] | None = None
    is_active: bool | None = None
    is_verified: bool | None = None
    region: str | None = Field(None, description="Filtrer par région administrative")
    city: str | None = Field(None, description="Filtrer par ville")

    # Pagination
    skip: int = Field(default=0, ge=0, description="Nombre d'éléments à sauter")
    limit: int = Field(
        default=20, ge=1, le=100, description="Nombre maximum d'éléments à retourner"
    )


class PatientListResponse(BaseModel):
    """Réponse paginée pour liste de patients."""

    items: list[PatientListItem] = Field(..., description="Liste des patients")
    total: int = Field(..., ge=0, description="Nombre total de résultats")
    skip: int = Field(..., ge=0, description="Nombre d'éléments sautés")
    limit: int = Field(..., ge=1, description="Limite par page")
