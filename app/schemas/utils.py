"""Annotations Pydantic réutilisables pour validation.

Ce module centralise les types annotés pour assurer la cohérence
de la validation à travers tous les schémas Pydantic du service.
"""

from typing import Annotated
from pydantic import EmailStr, Field, StringConstraints

# Types de base avec validation
PositiveInt = Annotated[int, Field(gt=0, description="Entier positif")]
NonNegativeInt = Annotated[int, Field(ge=0, description="Entier non-négatif")]

# Chaînes avec contraintes
NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]

# Téléphones internationaux (format E.164)
PhoneNumber = Annotated[
    str,
    StringConstraints(
        pattern=r"^\+[1-9]\d{1,14}$",
        strip_whitespace=True,
    ),
    Field(
        description="Numéro de téléphone au format international E.164 (ex: +221771234567)",
        examples=["+221771234567", "+33612345678"]
    )
]

# Identifiants
PatientId = Annotated[int, Field(gt=0, description="ID unique du patient")]
ProfessionalId = Annotated[int, Field(gt=0, description="ID unique du professionnel de santé")]

# Métadonnées
Email = Annotated[EmailStr, Field(description="Adresse email valide")]
Description = Annotated[str, Field(max_length=2000, description="Description texte")]
Title = Annotated[str, Field(min_length=1, max_length=255, description="Titre")]

# Données démographiques
AgeYears = Annotated[int, Field(ge=0, le=150, description="Âge en années")]

# Coordonnées GPS (format décimal)
Latitude = Annotated[
    float,
    Field(ge=-90.0, le=90.0, description="Latitude GPS en degrés décimaux")
]
Longitude = Annotated[
    float,
    Field(ge=-180.0, le=180.0, description="Longitude GPS en degrés décimaux")
]

# Identifiant national (Sénégal: Carte d'identité nationale, etc.)
NationalId = Annotated[
    str,
    StringConstraints(min_length=5, max_length=50, strip_whitespace=True),
    Field(description="Numéro d'identification nationale")
]
