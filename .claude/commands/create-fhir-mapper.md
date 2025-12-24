---
name: create-fhir-mapper
description: Crée un mapper bidirectionnel Pydantic vers FHIR R4 pour Patient ou Practitioner
---

# Créer un Mapper FHIR AfriCare

Cette commande génère un mapper bidirectionnel entre les schémas Pydantic du projet et les ressources FHIR R4. Le mapper gère la conversion des données démographiques vers HAPI FHIR (source de vérité).

## Utilisation

```
/create-fhir-mapper <type_resource> [Patient|Practitioner|RelatedPerson]
```

**Exemples:**
- `/create-fhir-mapper Patient` - Mapper pour Patient FHIR
- `/create-fhir-mapper Practitioner` - Mapper pour Practitioner FHIR

## Architecture Hybride FHIR

```
Client → API (Pydantic) → Mapper → HAPI FHIR (stockage)
                              ↓
                     PostgreSQL (métadonnées GDPR)
```

- **HAPI FHIR**: Source de vérité pour données démographiques
- **PostgreSQL**: Métadonnées GDPR locales (soft_deleted_at, correlation_hash, etc.)

## Systèmes d'Identifiants FHIR

**Fichier**: `app/infrastructure/fhir/identifiers.py`

```python
"""Systèmes d'identifiants FHIR pour AfriCare."""

# Authentification
KEYCLOAK_SYSTEM = "https://keycloak.africare.app/realms/africare"

# Identité nationale sénégalaise
NATIONAL_ID_SYSTEM = "http://senegal.gov.sn/nin"

# Licences professionnelles
PROFESSIONAL_LICENSE_SYSTEM = "http://senegal.gov.sn/professional-license"
CNOM_SYSTEM = "http://cnom.sn/registry"  # Conseil National de l'Ordre des Médecins
CNOP_SYSTEM = "http://cnop.sn/registry"  # Conseil National de l'Ordre des Pharmaciens

# Assurance maladie
CNAM_SYSTEM = "http://cnam.sn/beneficiary"  # Caisse Nationale d'Assurance Maladie
```

## Template Mapper Patient

**Fichier**: `app/infrastructure/fhir/mappers/patient_mapper.py`

```python
"""Mapper bidirectionnel Pydantic <-> FHIR Patient."""

from datetime import date
from typing import Optional

from fhir.resources.patient import Patient as FHIRPatient
from fhir.resources.identifier import Identifier
from fhir.resources.humanname import HumanName
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.address import Address

from app.infrastructure.fhir.identifiers import (
    KEYCLOAK_SYSTEM,
    NATIONAL_ID_SYSTEM,
)
from app.schemas.patient import PatientCreate, PatientResponse


class PatientMapper:
    """Mapper Patient: Pydantic <-> FHIR R4."""

    @staticmethod
    def to_fhir(data: PatientCreate, keycloak_user_id: str) -> FHIRPatient:
        """
        Convertit un schéma PatientCreate vers une ressource FHIR Patient.

        Args:
            data: Données de création du patient (Pydantic)
            keycloak_user_id: UUID Keycloak de l'utilisateur

        Returns:
            FHIRPatient: Ressource FHIR prête à envoyer à HAPI
        """
        # Identifiants
        identifiers = [
            Identifier(
                system=KEYCLOAK_SYSTEM,
                value=keycloak_user_id,
                use="official",
            )
        ]

        if data.national_id:
            identifiers.append(
                Identifier(
                    system=NATIONAL_ID_SYSTEM,
                    value=data.national_id,
                    use="official",
                )
            )

        # Contacts
        telecoms = []
        if data.phone:
            telecoms.append(
                ContactPoint(
                    system="phone",
                    value=data.phone,
                    use="mobile",
                )
            )
        if data.email:
            telecoms.append(
                ContactPoint(
                    system="email",
                    value=data.email,
                    use="home",
                )
            )

        # Adresse
        addresses = None
        if data.city or data.country:
            addresses = [
                Address(
                    city=data.city,
                    country=data.country or "SN",
                    use="home",
                )
            ]

        # Construction ressource FHIR
        return FHIRPatient(
            identifier=identifiers,
            active=True,
            name=[
                HumanName(
                    family=data.last_name,
                    given=[data.first_name],
                    use="official",
                )
            ],
            telecom=telecoms if telecoms else None,
            gender=data.gender if data.gender else None,
            birthDate=data.date_of_birth.isoformat() if data.date_of_birth else None,
            address=addresses,
            communication=[
                {
                    "language": {
                        "coding": [
                            {
                                "system": "urn:ietf:bcp:47",
                                "code": data.preferred_language or "fr",
                            }
                        ]
                    },
                    "preferred": True,
                }
            ],
        )

    @staticmethod
    def from_fhir(
        fhir_patient: FHIRPatient,
        local_id: int,
        gdpr_metadata: dict | None = None,
    ) -> PatientResponse:
        """
        Convertit une ressource FHIR Patient vers un schéma PatientResponse.

        Args:
            fhir_patient: Ressource FHIR Patient depuis HAPI
            local_id: ID numérique local (pour rétro-compatibilité API)
            gdpr_metadata: Métadonnées GDPR depuis PostgreSQL

        Returns:
            PatientResponse: Schéma Pydantic pour l'API
        """
        # Extraction identifiants
        keycloak_user_id = None
        national_id = None

        for identifier in fhir_patient.identifier or []:
            if identifier.system == KEYCLOAK_SYSTEM:
                keycloak_user_id = identifier.value
            elif identifier.system == NATIONAL_ID_SYSTEM:
                national_id = identifier.value

        # Extraction nom
        first_name = None
        last_name = None
        if fhir_patient.name:
            name = fhir_patient.name[0]
            last_name = name.family
            first_name = name.given[0] if name.given else None

        # Extraction contacts
        phone = None
        email = None
        for telecom in fhir_patient.telecom or []:
            if telecom.system == "phone":
                phone = telecom.value
            elif telecom.system == "email":
                email = telecom.value

        # Extraction langue préférée
        preferred_language = "fr"
        if fhir_patient.communication:
            comm = fhir_patient.communication[0]
            if comm.language and comm.language.coding:
                preferred_language = comm.language.coding[0].code

        # Construction réponse
        return PatientResponse(
            id=local_id,
            keycloak_user_id=keycloak_user_id,
            fhir_resource_id=fhir_patient.id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            national_id=national_id,
            gender=fhir_patient.gender,
            date_of_birth=(
                date.fromisoformat(fhir_patient.birthDate)
                if fhir_patient.birthDate
                else None
            ),
            preferred_language=preferred_language,
            is_active=fhir_patient.active if fhir_patient.active is not None else True,
            **(gdpr_metadata or {}),
        )
```

## Template Mapper Practitioner

**Fichier**: `app/infrastructure/fhir/mappers/professional_mapper.py`

```python
"""Mapper bidirectionnel Pydantic <-> FHIR Practitioner."""

from datetime import date
from typing import Optional

from fhir.resources.practitioner import Practitioner as FHIRPractitioner
from fhir.resources.identifier import Identifier
from fhir.resources.humanname import HumanName
from fhir.resources.contactpoint import ContactPoint

from app.infrastructure.fhir.identifiers import (
    KEYCLOAK_SYSTEM,
    NATIONAL_ID_SYSTEM,
    PROFESSIONAL_LICENSE_SYSTEM,
    CNOM_SYSTEM,
)
from app.schemas.professional import ProfessionalCreate, ProfessionalResponse


class ProfessionalMapper:
    """Mapper Professional: Pydantic <-> FHIR Practitioner R4."""

    @staticmethod
    def to_fhir(data: ProfessionalCreate, keycloak_user_id: str) -> FHIRPractitioner:
        """
        Convertit un schéma ProfessionalCreate vers FHIR Practitioner.

        Args:
            data: Données de création du professionnel (Pydantic)
            keycloak_user_id: UUID Keycloak de l'utilisateur

        Returns:
            FHIRPractitioner: Ressource FHIR prête à envoyer à HAPI
        """
        # Identifiants
        identifiers = [
            Identifier(
                system=KEYCLOAK_SYSTEM,
                value=keycloak_user_id,
                use="official",
            )
        ]

        if data.professional_id:
            identifiers.append(
                Identifier(
                    system=CNOM_SYSTEM,
                    value=data.professional_id,
                    use="official",
                )
            )

        if data.national_id:
            identifiers.append(
                Identifier(
                    system=NATIONAL_ID_SYSTEM,
                    value=data.national_id,
                    use="secondary",
                )
            )

        # Contacts
        telecoms = []
        if data.phone:
            telecoms.append(
                ContactPoint(
                    system="phone",
                    value=data.phone,
                    use="work",
                )
            )
        if data.email:
            telecoms.append(
                ContactPoint(
                    system="email",
                    value=data.email,
                    use="work",
                )
            )

        # Préfixe de nom (titre)
        prefix = [data.title] if data.title else None

        # Construction ressource FHIR
        return FHIRPractitioner(
            identifier=identifiers,
            active=True,
            name=[
                HumanName(
                    family=data.last_name,
                    given=[data.first_name],
                    prefix=prefix,
                    use="official",
                )
            ],
            telecom=telecoms if telecoms else None,
            gender=data.gender if data.gender else None,
            birthDate=data.date_of_birth.isoformat() if data.date_of_birth else None,
            qualification=[
                {
                    "code": {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "display": data.specialty,
                            }
                        ],
                        "text": data.specialty,
                    }
                }
            ]
            if data.specialty
            else None,
        )

    @staticmethod
    def from_fhir(
        fhir_practitioner: FHIRPractitioner,
        local_id: int,
        gdpr_metadata: dict | None = None,
    ) -> ProfessionalResponse:
        """
        Convertit une ressource FHIR Practitioner vers ProfessionalResponse.

        Args:
            fhir_practitioner: Ressource FHIR Practitioner depuis HAPI
            local_id: ID numérique local (pour rétro-compatibilité API)
            gdpr_metadata: Métadonnées GDPR depuis PostgreSQL

        Returns:
            ProfessionalResponse: Schéma Pydantic pour l'API
        """
        # Extraction identifiants
        keycloak_user_id = None
        professional_id = None
        national_id = None

        for identifier in fhir_practitioner.identifier or []:
            if identifier.system == KEYCLOAK_SYSTEM:
                keycloak_user_id = identifier.value
            elif identifier.system == CNOM_SYSTEM:
                professional_id = identifier.value
            elif identifier.system == NATIONAL_ID_SYSTEM:
                national_id = identifier.value

        # Extraction nom
        first_name = None
        last_name = None
        title = None
        if fhir_practitioner.name:
            name = fhir_practitioner.name[0]
            last_name = name.family
            first_name = name.given[0] if name.given else None
            title = name.prefix[0] if name.prefix else None

        # Extraction contacts
        phone = None
        email = None
        for telecom in fhir_practitioner.telecom or []:
            if telecom.system == "phone":
                phone = telecom.value
            elif telecom.system == "email":
                email = telecom.value

        # Extraction spécialité
        specialty = None
        if fhir_practitioner.qualification:
            qual = fhir_practitioner.qualification[0]
            if qual.code and qual.code.text:
                specialty = qual.code.text

        # Construction réponse
        return ProfessionalResponse(
            id=local_id,
            keycloak_user_id=keycloak_user_id,
            fhir_resource_id=fhir_practitioner.id,
            first_name=first_name,
            last_name=last_name,
            title=title,
            email=email,
            phone=phone,
            professional_id=professional_id,
            national_id=national_id,
            specialty=specialty,
            gender=fhir_practitioner.gender,
            date_of_birth=(
                date.fromisoformat(fhir_practitioner.birthDate)
                if fhir_practitioner.birthDate
                else None
            ),
            is_active=(
                fhir_practitioner.active
                if fhir_practitioner.active is not None
                else True
            ),
            **(gdpr_metadata or {}),
        )
```

## Pattern d'Orchestration

```python
"""Service d'identité avec orchestration FHIR."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.fhir.client import FHIRClient
from app.infrastructure.fhir.mappers.patient_mapper import PatientMapper
from app.models.gdpr_metadata import PatientGdprMetadata
from app.schemas.patient import PatientCreate, PatientResponse


async def create_patient(
    db: AsyncSession,
    fhir_client: FHIRClient,
    patient_data: PatientCreate,
    keycloak_user_id: str,
) -> PatientResponse:
    """
    Crée un patient avec orchestration HAPI FHIR + PostgreSQL.

    Workflow:
    1. Mapper vers FHIR
    2. Créer dans HAPI FHIR
    3. Créer métadonnées GDPR locales
    4. Retourner avec ID numérique local
    """
    # 1. Mapper vers FHIR
    fhir_patient = PatientMapper.to_fhir(patient_data, keycloak_user_id)

    # 2. Créer dans HAPI FHIR
    created_fhir = await fhir_client.create(fhir_patient)

    # 3. Créer métadonnées GDPR locales
    gdpr = PatientGdprMetadata(
        fhir_resource_id=created_fhir.id,
        keycloak_user_id=keycloak_user_id,
        is_verified=False,
    )
    db.add(gdpr)
    await db.commit()
    await db.refresh(gdpr)

    # 4. Retourner avec mapping inverse
    return PatientMapper.from_fhir(
        created_fhir,
        local_id=gdpr.id,
        gdpr_metadata={
            "is_verified": gdpr.is_verified,
            "created_at": gdpr.created_at,
            "updated_at": gdpr.updated_at,
        },
    )
```

## Checklist

- [ ] Créer `app/infrastructure/fhir/identifiers.py` avec systèmes
- [ ] Créer le mapper dans `app/infrastructure/fhir/mappers/`
- [ ] Ajouter les imports dans `app/infrastructure/fhir/__init__.py`
- [ ] Créer les tests dans `tests/unit/test_{resource}_mapper.py`
- [ ] Exécuter `make lint` et `make test`

## Ressources

- **Client FHIR**: `app/infrastructure/fhir/client.py`
- **Documentation**: `docs/fhir-architecture.md`
- **FHIR R4 spec**: https://hl7.org/fhir/R4/
- **fhir.resources**: https://pypi.org/project/fhir.resources/
