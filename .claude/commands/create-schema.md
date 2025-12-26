---
name: create-schema
description: Génère des schémas Pydantic 2.0 avec annotations réutilisables et validation avancée
---

# Créer des Schémas Pydantic AfriCare

Cette commande génère des schémas Pydantic 2.0 complets suivant les patterns AfriCare. Elle crée les schémas de base, création, mise à jour et réponse avec annotations réutilisables et validation avancée.

## Utilisation

```
/create-schema <nom_entite> [description]
```

**Exemples:**
- `/create-schema patient` - Créer les schémas Patient
- `/create-schema professional` - Créer les schémas Professional
- `/create-schema appointment` - Créer les schémas Appointment

## Template Schémas Complet

### Structure de fichier

**Fichier**: `app/schemas/{entity}.py`

```python
"""Schémas Pydantic pour {Entity}."""

from datetime import date, datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.utils import (
    NonEmptyStr,
    PhoneNumber,
    PositiveInt,
)


# Types spécifiques à l'entité
{Entity}Status = Literal["active", "inactive", "pending", "suspended"]
DeletionReason = Literal[
    "user_request",
    "admin_termination",
    "professional_revocation",
    "gdpr_compliance",
    "prolonged_inactivity",
]


class {Entity}Base(BaseModel):
    """
    Schéma de base pour {Entity}.

    Contient les champs communs partagés entre création, mise à jour et réponse.
    """

    first_name: NonEmptyStr = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Prénom",
        examples=["Amadou"],
    )
    last_name: NonEmptyStr = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Nom de famille",
        examples=["Diallo"],
    )
    email: EmailStr = Field(
        ...,
        description="Adresse email valide",
        examples=["amadou.diallo@example.sn"],
    )
    phone: Optional[PhoneNumber] = Field(
        None,
        description="Numéro de téléphone (format international)",
        examples=["+221771234567"],
    )
    date_of_birth: Optional[date] = Field(
        None,
        description="Date de naissance",
        examples=["1990-05-15"],
    )
    gender: Optional[Literal["male", "female", "other", "unknown"]] = Field(
        None,
        description="Genre",
    )


class {Entity}Create({Entity}Base):
    """
    Schéma pour la création d'un(e) {Entity}.

    Hérite de {Entity}Base et ajoute les champs requis à la création.
    """

    # Champs additionnels pour création
    national_id: Optional[str] = Field(
        None,
        pattern=r"^[A-Z0-9]{10,20}$",
        description="Numéro d'identité nationale",
        examples=["SN1234567890"],
    )
    preferred_language: Literal["fr", "wo", "en"] = Field(
        default="fr",
        description="Langue préférée (fr=Français, wo=Wolof, en=Anglais)",
    )

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, v: Optional[date]) -> Optional[date]:
        """Valide que la date de naissance est dans le passé."""
        if v is not None and v > date.today():
            raise ValueError("La date de naissance doit être dans le passé")
        return v


class {Entity}Update(BaseModel):
    """
    Schéma pour la mise à jour d'un(e) {Entity}.

    Tous les champs sont optionnels pour permettre des mises à jour partielles.
    """

    first_name: Optional[NonEmptyStr] = Field(
        None,
        min_length=1,
        max_length=100,
    )
    last_name: Optional[NonEmptyStr] = Field(
        None,
        min_length=1,
        max_length=100,
    )
    email: Optional[EmailStr] = None
    phone: Optional[PhoneNumber] = None
    date_of_birth: Optional[date] = None
    gender: Optional[Literal["male", "female", "other", "unknown"]] = None
    preferred_language: Optional[Literal["fr", "wo", "en"]] = None

    model_config = ConfigDict(
        # Permet les valeurs None explicites vs non-définies
        extra="forbid",
    )


class {Entity}Response({Entity}Base):
    """
    Schéma de réponse pour {Entity}.

    Inclut tous les champs de base plus les métadonnées système.
    """

    id: PositiveInt = Field(..., description="Identifiant unique")
    keycloak_user_id: str = Field(
        ...,
        description="UUID Keycloak",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    is_active: bool = Field(default=True, description="Entité active")
    created_at: datetime = Field(..., description="Date de création")
    updated_at: datetime = Field(..., description="Date de dernière modification")

    # Champs GDPR (optionnels dans la réponse)
    soft_deleted_at: Optional[datetime] = Field(
        None,
        description="Date de suppression douce (si applicable)",
    )

    model_config = ConfigDict(
        from_attributes=True,  # Permet la conversion depuis SQLAlchemy
        json_encoders={
            datetime: lambda v: v.isoformat(),
            date: lambda v: v.isoformat(),
        },
    )


class {Entity}List(BaseModel):
    """Schéma pour liste paginée de {Entity}s."""

    items: list[{Entity}Response] = Field(default_factory=list)
    total: int = Field(..., ge=0, description="Nombre total d'éléments")
    page: int = Field(default=1, ge=1, description="Page courante")
    page_size: int = Field(default=20, ge=1, le=100, description="Taille de page")
    pages: int = Field(..., ge=0, description="Nombre total de pages")


# Schémas spécialisés pour opérations admin
class {Entity}DeletionRequest(BaseModel):
    """Schéma pour demande de suppression."""

    deletion_reason: DeletionReason = Field(
        ...,
        description="Raison de la suppression",
    )
    investigation_check_override: bool = Field(
        default=False,
        description="Ignorer le blocage d'enquête (admin uniquement)",
    )
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Notes additionnelles",
    )


class {Entity}RestoreRequest(BaseModel):
    """Schéma pour demande de restauration (période de grâce)."""

    restore_reason: NonEmptyStr = Field(
        ...,
        max_length=500,
        description="Raison de la restauration",
    )
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Notes additionnelles",
    )


class {Entity}InvestigationUpdate(BaseModel):
    """Schéma pour mise à jour du statut d'enquête."""

    under_investigation: bool = Field(
        ...,
        description="Professionnel sous enquête",
    )
    investigation_notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Notes d'enquête (confidentielles)",
    )
```

## Annotations Réutilisables

**Fichier**: `app/schemas/utils.py`

```python
"""Annotations Pydantic réutilisables pour validation."""

from typing import Annotated

from pydantic import Field, StringConstraints


# Types de base avec validation
PositiveInt = Annotated[int, Field(gt=0, description="Entier positif")]
NonNegativeInt = Annotated[int, Field(ge=0, description="Entier non-négatif")]
PositiveFloat = Annotated[float, Field(gt=0.0, description="Flottant positif")]

# Chaînes avec contraintes
NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
PhoneNumber = Annotated[str, StringConstraints(pattern=r"^\+?[1-9]\d{1,14}$")]
PostalCode = Annotated[str, StringConstraints(pattern=r"^\d{5}$")]

# Identifiants
PatientId = Annotated[int, Field(gt=0, description="ID unique du patient")]
ProfessionalId = Annotated[int, Field(gt=0, description="ID unique du professionnel")]
AppointmentId = Annotated[int, Field(gt=0, description="ID unique du rendez-vous")]

# Plages de valeurs
AgeYears = Annotated[int, Field(ge=0, le=150, description="Âge en années")]
Percentage = Annotated[float, Field(ge=0.0, le=100.0, description="Pourcentage 0-100")]
```

## Intégration

**Ajouter dans** `app/schemas/__init__.py`:

```python
from app.schemas.{entity} import (
    {Entity}Base,
    {Entity}Create,
    {Entity}DeletionRequest,
    {Entity}InvestigationUpdate,
    {Entity}List,
    {Entity}Response,
    {Entity}RestoreRequest,
    {Entity}Update,
)

__all__ = [
    # ... autres schémas
    "{Entity}Base",
    "{Entity}Create",
    "{Entity}Update",
    "{Entity}Response",
    "{Entity}List",
    "{Entity}DeletionRequest",
    "{Entity}RestoreRequest",
    "{Entity}InvestigationUpdate",
]
```

## Checklist

- [ ] Créer/vérifier `app/schemas/utils.py` avec annotations réutilisables
- [ ] Créer le fichier schémas `app/schemas/{entity}.py`
- [ ] Ajouter les imports dans `app/schemas/__init__.py`
- [ ] Exécuter `make lint` et `make test`

## Conventions AfriCare

### Hiérarchie des Schémas

```
{Entity}Base
    ├── {Entity}Create (hérite)
    └── {Entity}Response (hérite)

{Entity}Update (standalone, tous champs optionnels)
{Entity}List (composition avec {Entity}Response)
```

### Literal vs Enum

**Toujours** utiliser `typing.Literal[]` pour les valeurs fixes:

```python
# Correct
status: Literal["active", "inactive", "pending"]

# Incorrect (éviter les Enum)
class Status(str, Enum):
    ACTIVE = "active"
```

### Annotated pour Réutilisabilité

Centraliser les validations dans `app/schemas/utils.py`:

```python
# Dans utils.py
PhoneNumber = Annotated[str, StringConstraints(pattern=r"^\+?[1-9]\d{1,14}$")]

# Dans entity.py
phone: Optional[PhoneNumber] = None
```

### Validation avec field_validator

```python
@field_validator("date_of_birth")
@classmethod
def validate_date_of_birth(cls, v: Optional[date]) -> Optional[date]:
    if v is not None and v > date.today():
        raise ValueError("La date de naissance doit être dans le passé")
    return v
```

### Configuration Modèle

```python
model_config = ConfigDict(
    from_attributes=True,      # Conversion SQLAlchemy -> Pydantic
    extra="forbid",            # Rejeter champs inconnus
    json_encoders={            # Sérialisation custom
        datetime: lambda v: v.isoformat(),
    },
)
```

## Ressources

- **Patterns Pydantic**: Voir `CLAUDE.md` section "Pydantic schema"
- **Annotations**: Voir `app/schemas/utils.py`
- **Exemples**: Voir `app/schemas/patient.py` et `app/schemas/professional.py`
