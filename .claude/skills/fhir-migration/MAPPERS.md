# Mappers Pydantic ↔ FHIR

Ce document contient les templates de mappers bidirectionnels.

## Structure des Mappers

```
app/infrastructure/fhir/mappers/
├── __init__.py
├── patient_mapper.py
└── professional_mapper.py
```

## Patient Mapper

**Fichier**: `app/infrastructure/fhir/mappers/patient_mapper.py`

```python
"""Mapper bidirectionnel Pydantic <-> FHIR Patient."""

from datetime import date

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
        Convertit PatientCreate vers FHIR Patient.

        Args:
            data: Données de création (Pydantic)
            keycloak_user_id: UUID Keycloak

        Returns:
            FHIRPatient prête pour HAPI
        """
        # Identifiants
        identifiers = [
            Identifier(system=KEYCLOAK_SYSTEM, value=keycloak_user_id, use="official")
        ]
        if data.national_id:
            identifiers.append(
                Identifier(system=NATIONAL_ID_SYSTEM, value=data.national_id, use="official")
            )

        # Contacts
        telecoms = []
        if data.phone:
            telecoms.append(ContactPoint(system="phone", value=data.phone, use="mobile"))
        if data.email:
            telecoms.append(ContactPoint(system="email", value=data.email, use="home"))

        # Adresse
        addresses = None
        if data.city or data.country:
            addresses = [Address(city=data.city, country=data.country or "SN", use="home")]

        # Construction
        return FHIRPatient(
            identifier=identifiers,
            active=True,
            name=[HumanName(family=data.last_name, given=[data.first_name], use="official")],
            telecom=telecoms if telecoms else None,
            gender=data.gender,
            birthDate=data.date_of_birth.isoformat() if data.date_of_birth else None,
            address=addresses,
            communication=[{
                "language": {"coding": [{"system": "urn:ietf:bcp:47", "code": data.preferred_language or "fr"}]},
                "preferred": True,
            }],
        )

    @staticmethod
    def from_fhir(
        fhir_patient: FHIRPatient,
        local_id: int,
        gdpr_metadata: dict | None = None,
    ) -> PatientResponse:
        """
        Convertit FHIR Patient vers PatientResponse.

        Args:
            fhir_patient: Ressource FHIR
            local_id: ID numérique local
            gdpr_metadata: Métadonnées GDPR

        Returns:
            PatientResponse pour l'API
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
        first_name = last_name = None
        if fhir_patient.name:
            name = fhir_patient.name[0]
            last_name = name.family
            first_name = name.given[0] if name.given else None

        # Extraction contacts
        phone = email = None
        for telecom in fhir_patient.telecom or []:
            if telecom.system == "phone":
                phone = telecom.value
            elif telecom.system == "email":
                email = telecom.value

        # Extraction langue
        preferred_language = "fr"
        if fhir_patient.communication:
            comm = fhir_patient.communication[0]
            if comm.language and comm.language.coding:
                preferred_language = comm.language.coding[0].code

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
            date_of_birth=date.fromisoformat(fhir_patient.birthDate) if fhir_patient.birthDate else None,
            preferred_language=preferred_language,
            is_active=fhir_patient.active if fhir_patient.active is not None else True,
            **(gdpr_metadata or {}),
        )
```

## Professional Mapper

**Fichier**: `app/infrastructure/fhir/mappers/professional_mapper.py`

```python
"""Mapper bidirectionnel Pydantic <-> FHIR Practitioner."""

from datetime import date

from fhir.resources.practitioner import Practitioner as FHIRPractitioner
from fhir.resources.identifier import Identifier
from fhir.resources.humanname import HumanName
from fhir.resources.contactpoint import ContactPoint

from app.infrastructure.fhir.identifiers import (
    KEYCLOAK_SYSTEM,
    NATIONAL_ID_SYSTEM,
    CNOM_SYSTEM,
)
from app.schemas.professional import ProfessionalCreate, ProfessionalResponse


class ProfessionalMapper:
    """Mapper Professional: Pydantic <-> FHIR Practitioner R4."""

    @staticmethod
    def to_fhir(data: ProfessionalCreate, keycloak_user_id: str) -> FHIRPractitioner:
        """Convertit ProfessionalCreate vers FHIR Practitioner."""
        # Identifiants
        identifiers = [
            Identifier(system=KEYCLOAK_SYSTEM, value=keycloak_user_id, use="official")
        ]
        if data.professional_id:
            identifiers.append(
                Identifier(system=CNOM_SYSTEM, value=data.professional_id, use="official")
            )
        if data.national_id:
            identifiers.append(
                Identifier(system=NATIONAL_ID_SYSTEM, value=data.national_id, use="secondary")
            )

        # Contacts
        telecoms = []
        if data.phone:
            telecoms.append(ContactPoint(system="phone", value=data.phone, use="work"))
        if data.email:
            telecoms.append(ContactPoint(system="email", value=data.email, use="work"))

        # Préfixe
        prefix = [data.title] if data.title else None

        # Qualification
        qualification = None
        if data.specialty:
            qualification = [{
                "code": {
                    "coding": [{"system": "http://snomed.info/sct", "display": data.specialty}],
                    "text": data.specialty,
                }
            }]

        return FHIRPractitioner(
            identifier=identifiers,
            active=True,
            name=[HumanName(family=data.last_name, given=[data.first_name], prefix=prefix, use="official")],
            telecom=telecoms if telecoms else None,
            gender=data.gender,
            birthDate=data.date_of_birth.isoformat() if data.date_of_birth else None,
            qualification=qualification,
        )

    @staticmethod
    def from_fhir(
        fhir_practitioner: FHIRPractitioner,
        local_id: int,
        gdpr_metadata: dict | None = None,
    ) -> ProfessionalResponse:
        """Convertit FHIR Practitioner vers ProfessionalResponse."""
        # Extraction identifiants
        keycloak_user_id = professional_id = national_id = None
        for identifier in fhir_practitioner.identifier or []:
            if identifier.system == KEYCLOAK_SYSTEM:
                keycloak_user_id = identifier.value
            elif identifier.system == CNOM_SYSTEM:
                professional_id = identifier.value
            elif identifier.system == NATIONAL_ID_SYSTEM:
                national_id = identifier.value

        # Extraction nom
        first_name = last_name = title = None
        if fhir_practitioner.name:
            name = fhir_practitioner.name[0]
            last_name = name.family
            first_name = name.given[0] if name.given else None
            title = name.prefix[0] if name.prefix else None

        # Extraction contacts
        phone = email = None
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
            date_of_birth=date.fromisoformat(fhir_practitioner.birthDate) if fhir_practitioner.birthDate else None,
            is_active=fhir_practitioner.active if fhir_practitioner.active is not None else True,
            **(gdpr_metadata or {}),
        )
```

## Tests Mappers

**Fichier**: `tests/unit/test_fhir_mappers.py`

```python
"""Tests pour les mappers FHIR."""

import pytest
from datetime import date

from app.infrastructure.fhir.mappers.patient_mapper import PatientMapper
from app.schemas.patient import PatientCreate


class TestPatientMapper:
    """Tests PatientMapper."""

    def test_to_fhir_minimal(self):
        """Test conversion minimale vers FHIR."""
        data = PatientCreate(
            first_name="Amadou",
            last_name="Diallo",
            email="amadou@example.sn",
        )
        keycloak_id = "test-uuid-123"

        result = PatientMapper.to_fhir(data, keycloak_id)

        assert result.active is True
        assert result.name[0].family == "Diallo"
        assert result.name[0].given == ["Amadou"]
        assert len(result.identifier) == 1  # Only Keycloak

    def test_to_fhir_complete(self):
        """Test conversion complète vers FHIR."""
        data = PatientCreate(
            first_name="Fatou",
            last_name="Sow",
            email="fatou@example.sn",
            phone="+221771234567",
            national_id="SN123456789",
            date_of_birth=date(1990, 5, 15),
            gender="female",
            preferred_language="wo",
        )
        keycloak_id = "test-uuid-456"

        result = PatientMapper.to_fhir(data, keycloak_id)

        assert len(result.identifier) == 2  # Keycloak + NIN
        assert result.gender == "female"
        assert result.birthDate == "1990-05-15"

    def test_from_fhir_roundtrip(self):
        """Test aller-retour Pydantic -> FHIR -> Pydantic."""
        data = PatientCreate(
            first_name="Moussa",
            last_name="Ba",
            email="moussa@example.sn",
            phone="+221771234567",
        )
        keycloak_id = "test-uuid-789"

        # Aller
        fhir = PatientMapper.to_fhir(data, keycloak_id)
        fhir.id = "fhir-resource-id"

        # Retour
        response = PatientMapper.from_fhir(fhir, local_id=42)

        assert response.id == 42
        assert response.first_name == "Moussa"
        assert response.last_name == "Ba"
        assert response.email == "moussa@example.sn"
```
