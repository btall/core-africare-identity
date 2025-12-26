# Systèmes d'Identifiants FHIR AfriCare

Ce document définit les systèmes d'identifiants FHIR utilisés dans le contexte sénégalais.

## Vue d'Ensemble

```
Keycloak                          FHIR
┌─────────────────┐               ┌─────────────────────┐
│ User            │               │ Patient             │
│  sub: uuid-123  │──────────────→│  identifier[]:      │
│                 │               │   - keycloak.system │
│ attributes:     │               │   - nin-senegal     │
│  fhir_patient_id│←──────────────│  id: pat-001        │
└─────────────────┘               └─────────────────────┘
```

## Fichier d'Implémentation

**Fichier**: `app/infrastructure/fhir/identifiers.py`

```python
"""
Systèmes d'identifiants FHIR pour AfriCare (contexte sénégalais).

Ces systèmes permettent d'identifier de manière unique les ressources
FHIR et de les lier aux systèmes externes (Keycloak, registres nationaux).
"""

# =============================================================================
# AUTHENTIFICATION KEYCLOAK
# =============================================================================

# Système d'identification Keycloak (lien User → Patient/Practitioner)
KEYCLOAK_SYSTEM = "https://keycloak.africare.app/realms/africare"
"""
Identifie l'utilisateur Keycloak associé à une ressource Patient ou Practitioner.
Valeur: UUID Keycloak (sub du JWT)
Exemple: "550e8400-e29b-41d4-a716-446655440000"
"""

# =============================================================================
# IDENTITÉ NATIONALE SÉNÉGALAISE
# =============================================================================

# Numéro d'Identification Nationale (NIN)
NIN_SYSTEM = "https://africare.app/fhir/sid/nin-senegal"
"""
Numéro d'Identification Nationale du Sénégal.
Obligatoire pour les citoyens sénégalais.
Format: 13 chiffres
Exemple: "1234567890123"
"""

# =============================================================================
# ORDRES PROFESSIONNELS
# =============================================================================

# Conseil National de l'Ordre des Médecins du Sénégal
CNOM_SYSTEM = "https://ordre-medecins.sn/fhir/sid/licence"
"""
Numéro d'inscription à l'Ordre des Médecins.
Obligatoire pour exercer la médecine au Sénégal.
Format: MED-YYYY-NNNNN
Exemple: "MED-2015-04521"
"""

# Conseil National de l'Ordre des Pharmaciens
CNOP_SYSTEM = "https://ordre-pharmaciens.sn/fhir/sid/licence"
"""
Numéro d'inscription à l'Ordre des Pharmaciens.
Format: PHARM-YYYY-NNNNN
Exemple: "PHARM-2018-00123"
"""

# Ordre des Infirmiers et Infirmières du Sénégal
ONIS_SYSTEM = "https://ordre-infirmiers.sn/fhir/sid/licence"
"""
Numéro d'inscription à l'Ordre des Infirmiers.
Format: INF-YYYY-NNNNN
"""

# Ordre des Sages-Femmes du Sénégal
OSFDS_SYSTEM = "https://ordre-sages-femmes.sn/fhir/sid/licence"
"""
Numéro d'inscription à l'Ordre des Sages-Femmes.
Format: SF-YYYY-NNNNN
"""

# =============================================================================
# ÉTABLISSEMENTS DE SANTÉ
# =============================================================================

# FINESS Sénégalais (Fichier National des Établissements)
FINESS_SYSTEM = "https://sante.gouv.sn/fhir/sid/finess"
"""
Identifiant unique des établissements de santé au Sénégal.
Attribué par le Ministère de la Santé.
Format: SN-RR-DDD-NNNN (Région-Département-Numéro)
Exemple: "SN-14-001-0001" (CHU Fann)
"""

# =============================================================================
# ASSURANCE MALADIE
# =============================================================================

# Caisse Nationale d'Assurance Maladie (CNAM)
CNAM_SYSTEM = "https://cnam.sn/fhir/sid/beneficiary"
"""
Numéro de bénéficiaire CNAM.
Format: variable selon le régime
"""

# =============================================================================
# IDENTIFIANTS INTERNES AFRICARE
# =============================================================================

# Identifiant Patient AfriCare
AFRICARE_PATIENT_SYSTEM = "https://africare.app/fhir/sid/patient-id"
"""
Identifiant interne patient AfriCare.
Généré automatiquement.
Format: PAT-YYYY-NNNNN
Exemple: "PAT-2025-00001"
"""

# Identifiant Practitioner AfriCare
AFRICARE_PRACTITIONER_SYSTEM = "https://africare.app/fhir/sid/practitioner-id"
"""
Identifiant interne praticien AfriCare.
Généré automatiquement.
Format: PRACT-YYYY-NNNNN
Exemple: "PRACT-2024-00042"
"""

# Identifiant Organization AfriCare
AFRICARE_ORG_SYSTEM = "https://africare.app/fhir/sid/organization-id"
"""
Identifiant interne organisation AfriCare.
Doit correspondre à l'ID Keycloak Organization.
Format: org-{slug}
Exemple: "org-chu-fann"
"""

# Identifiant PractitionerRole AfriCare
AFRICARE_PR_SYSTEM = "https://africare.app/fhir/sid/practitioner-role-id"
"""
Identifiant interne PractitionerRole.
Format: PR-{org}-{year}-{number}
Exemple: "CHU-CARDIO-2020-015"
"""

# Identifiant Consent AfriCare
AFRICARE_CONSENT_SYSTEM = "https://africare.app/fhir/sid/consent"
"""
Identifiant interne consentement.
Format: CONS-YYYY-NNNNN
Exemple: "CONS-2025-00001"
"""

# =============================================================================
# DIPLÔMES ET QUALIFICATIONS
# =============================================================================

# Université Cheikh Anta Diop de Dakar
UCAD_DIPLOME_SYSTEM = "https://ucad.sn/fhir/sid/diplome"
"""
Numéro de diplôme UCAD.
Format: MED-YYYY-NNNN
"""

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_identifier(identifiers: list, system: str) -> str | None:
    """
    Extrait la valeur d'un identifiant par son système.

    Args:
        identifiers: Liste d'identifiants FHIR
        system: URI du système recherché

    Returns:
        Valeur de l'identifiant ou None
    """
    for identifier in identifiers or []:
        if identifier.system == system:
            return identifier.value
    return None


def create_identifier(
    system: str,
    value: str,
    use: str = "official",
    type_code: str | None = None,
    type_display: str | None = None,
) -> dict:
    """
    Crée un identifiant FHIR formaté.

    Args:
        system: URI du système
        value: Valeur de l'identifiant
        use: official, usual, secondary, temp
        type_code: Code du type (NI, MD, etc.)
        type_display: Libellé du type

    Returns:
        Dictionnaire identifiant FHIR
    """
    identifier = {
        "use": use,
        "system": system,
        "value": value,
    }

    if type_code:
        identifier["type"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                "code": type_code,
                "display": type_display or type_code,
            }]
        }

    return identifier


# Mapping type → système
PROFESSIONAL_SYSTEMS = {
    "physician": CNOM_SYSTEM,
    "pharmacist": CNOP_SYSTEM,
    "nurse": ONIS_SYSTEM,
    "midwife": OSFDS_SYSTEM,
}


def get_professional_license_system(professional_type: str) -> str:
    """
    Retourne le système d'identifiant pour un type de professionnel.

    Args:
        professional_type: Type de professionnel (physician, pharmacist, etc.)

    Returns:
        URI du système d'identifiant de licence
    """
    return PROFESSIONAL_SYSTEMS.get(professional_type, CNOM_SYSTEM)
```

## Utilisation dans les Mappers

```python
from app.infrastructure.fhir.identifiers import (
    KEYCLOAK_SYSTEM,
    NIN_SYSTEM,
    CNOM_SYSTEM,
    AFRICARE_PATIENT_SYSTEM,
    get_identifier,
    create_identifier,
)

# Création d'identifiants Patient
identifiers = [
    create_identifier(
        system=KEYCLOAK_SYSTEM,
        value=keycloak_user_id,
        use="official",
    ),
    create_identifier(
        system=NIN_SYSTEM,
        value="1234567890123",
        use="official",
        type_code="NI",
        type_display="National unique individual identifier",
    ),
    create_identifier(
        system=AFRICARE_PATIENT_SYSTEM,
        value="PAT-2025-00001",
        use="usual",
    ),
]

# Extraction depuis une ressource FHIR
keycloak_id = get_identifier(patient.identifier, KEYCLOAK_SYSTEM)
nin = get_identifier(patient.identifier, NIN_SYSTEM)
```

## Correspondance Keycloak ↔ FHIR

| Attribut Keycloak | Identifiant FHIR | Description |
|-------------------|------------------|-------------|
| `sub` (JWT) | `identifier[system=keycloak]` | Lien User → Patient/Practitioner |
| `fhir_patient_id` | `Patient.id` | ID ressource FHIR |
| `fhir_practitioner_id` | `Practitioner.id` | ID ressource FHIR |
| `organizations[].id` | `Organization.identifier` | Même ID (org-xxx) |

## Validation des Identifiants

```python
import re

def validate_nin(value: str) -> bool:
    """Valide un NIN sénégalais (13 chiffres)."""
    return bool(re.match(r"^\d{13}$", value))

def validate_cnom_license(value: str) -> bool:
    """Valide une licence CNOM (MED-YYYY-NNNNN)."""
    return bool(re.match(r"^MED-\d{4}-\d{5}$", value))

def validate_finess(value: str) -> bool:
    """Valide un FINESS sénégalais (SN-RR-DDD-NNNN)."""
    return bool(re.match(r"^SN-\d{2}-\d{3}-\d{4}$", value))
```
