---
name: identity-migrate-hapi-fhir
description: Migration du service core-africare-identity vers HAPI FHIR. Orchestre la gestion d'identité entre Keycloak et HAPI FHIR comme source de vérité pour Patient/Practitioner.
---

# Migration core-africare-identity vers HAPI FHIR

## Contexte

Ce microservice orchestre la gestion d'identité entre Keycloak (authentification) et HAPI FHIR (stockage des données démographiques cliniques). La migration supprime le stockage local des données Patient/Practitioner au profit de HAPI FHIR comme source de vérité.

## Architecture Cible

```
Client → Keycloak (auth) → core-africare-identity (orchestration) → HAPI FHIR (stockage Patient/Practitioner)
```

## Tâches à Exécuter

### 1. Dépendances

Ajouter dans `pyproject.toml` ou `requirements.txt`:

```
fhir.resources>=7.0.0
httpx>=0.27.0
```

### 2. Client HAPI FHIR

Créer `app/infrastructure/fhir/client.py`:

```python
from typing import Optional
import httpx
from fhir.resources.patient import Patient
from fhir.resources.practitioner import Practitioner
from fhir.resources.relatedperson import RelatedPerson
from pydantic_settings import BaseSettings

class FHIRSettings(BaseSettings):
    fhir_base_url: str = "http://hapi-fhir:8080/fhir"
    fhir_timeout: int = 30

    class Config:
        env_prefix = "AFRICARE_"

class FHIRClient:
    def __init__(self, settings: FHIRSettings):
        self.base_url = settings.fhir_base_url
        self.timeout = settings.fhir_timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={"Content-Type": "application/fhir+json"}
            )
        return self._client

    async def create_patient(self, patient: Patient) -> Patient:
        client = await self._get_client()
        response = await client.post("/Patient", content=patient.json())
        response.raise_for_status()
        return Patient.parse_raw(response.text)

    async def get_patient(self, patient_id: str) -> Optional[Patient]:
        client = await self._get_client()
        response = await client.get(f"/Patient/{patient_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return Patient.parse_raw(response.text)

    async def search_patient_by_identifier(self, system: str, value: str) -> Optional[Patient]:
        client = await self._get_client()
        response = await client.get("/Patient", params={"identifier": f"{system}|{value}"})
        response.raise_for_status()
        bundle = response.json()
        if bundle.get("total", 0) > 0:
            return Patient.parse_obj(bundle["entry"][0]["resource"])
        return None

    async def update_patient(self, patient_id: str, patient: Patient) -> Patient:
        client = await self._get_client()
        response = await client.put(f"/Patient/{patient_id}", content=patient.json())
        response.raise_for_status()
        return Patient.parse_raw(response.text)

    async def create_practitioner(self, practitioner: Practitioner) -> Practitioner:
        client = await self._get_client()
        response = await client.post("/Practitioner", content=practitioner.json())
        response.raise_for_status()
        return Practitioner.parse_raw(response.text)

    async def get_practitioner(self, practitioner_id: str) -> Optional[Practitioner]:
        client = await self._get_client()
        response = await client.get(f"/Practitioner/{practitioner_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return Practitioner.parse_raw(response.text)

    async def search_practitioner_by_identifier(self, system: str, value: str) -> Optional[Practitioner]:
        client = await self._get_client()
        response = await client.get("/Practitioner", params={"identifier": f"{system}|{value}"})
        response.raise_for_status()
        bundle = response.json()
        if bundle.get("total", 0) > 0:
            return Practitioner.parse_obj(bundle["entry"][0]["resource"])
        return None

    async def close(self):
        if self._client:
            await self._client.aclose()
```

### 3. Mappers Pydantic ↔ FHIR

Créer `app/infrastructure/fhir/mappers.py`:

```python
from typing import Optional, List
from datetime import date
from fhir.resources.patient import Patient
from fhir.resources.practitioner import Practitioner
from fhir.resources.identifier import Identifier
from fhir.resources.humanname import HumanName
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.address import Address

from app.domain.models import PatientCreate, PatientResponse, PractitionerCreate, PractitionerResponse

KEYCLOAK_SYSTEM = "https://keycloak.africare.app/realms/africare"
NATIONAL_ID_SYSTEM = "http://senegal.gov.sn/nin"
PROFESSIONAL_LICENSE_SYSTEM = "http://senegal.gov.sn/professional-license"

class PatientMapper:
    @staticmethod
    def to_fhir(data: PatientCreate, keycloak_sub: str) -> Patient:
        identifiers = [
            Identifier(system=KEYCLOAK_SYSTEM, value=keycloak_sub)
        ]
        if data.national_id:
            identifiers.append(Identifier(system=NATIONAL_ID_SYSTEM, value=data.national_id))

        telecoms = []
        if data.phone:
            telecoms.append(ContactPoint(system="phone", value=data.phone, use="mobile"))
        if data.email:
            telecoms.append(ContactPoint(system="email", value=data.email))

        return Patient(
            identifier=identifiers,
            active=True,
            name=[HumanName(family=data.last_name, given=[data.first_name])],
            telecom=telecoms if telecoms else None,
            gender=data.gender if data.gender else None,
            birthDate=data.birth_date.isoformat() if data.birth_date else None,
            address=[Address(
                city=data.city,
                country="SN"
            )] if data.city else None
        )

    @staticmethod
    def to_domain(patient: Patient) -> PatientResponse:
        keycloak_sub = None
        national_id = None
        for identifier in patient.identifier or []:
            if identifier.system == KEYCLOAK_SYSTEM:
                keycloak_sub = identifier.value
            elif identifier.system == NATIONAL_ID_SYSTEM:
                national_id = identifier.value

        name = patient.name[0] if patient.name else None
        phone = None
        email = None
        for telecom in patient.telecom or []:
            if telecom.system == "phone":
                phone = telecom.value
            elif telecom.system == "email":
                email = telecom.value

        return PatientResponse(
            id=patient.id,
            keycloak_sub=keycloak_sub,
            national_id=national_id,
            first_name=name.given[0] if name and name.given else None,
            last_name=name.family if name else None,
            email=email,
            phone=phone,
            gender=patient.gender,
            birth_date=date.fromisoformat(patient.birthDate) if patient.birthDate else None,
            active=patient.active
        )

class PractitionerMapper:
    @staticmethod
    def to_fhir(data: PractitionerCreate, keycloak_sub: str) -> Practitioner:
        identifiers = [
            Identifier(system=KEYCLOAK_SYSTEM, value=keycloak_sub)
        ]
        if data.professional_license:
            identifiers.append(Identifier(system=PROFESSIONAL_LICENSE_SYSTEM, value=data.professional_license))
        if data.national_id:
            identifiers.append(Identifier(system=NATIONAL_ID_SYSTEM, value=data.national_id))

        telecoms = []
        if data.phone:
            telecoms.append(ContactPoint(system="phone", value=data.phone, use="work"))
        if data.email:
            telecoms.append(ContactPoint(system="email", value=data.email, use="work"))

        return Practitioner(
            identifier=identifiers,
            active=True,
            name=[HumanName(family=data.last_name, given=[data.first_name], prefix=[data.title] if data.title else None)],
            telecom=telecoms if telecoms else None,
            gender=data.gender if data.gender else None,
            birthDate=data.birth_date.isoformat() if data.birth_date else None
        )

    @staticmethod
    def to_domain(practitioner: Practitioner) -> PractitionerResponse:
        keycloak_sub = None
        professional_license = None
        national_id = None
        for identifier in practitioner.identifier or []:
            if identifier.system == KEYCLOAK_SYSTEM:
                keycloak_sub = identifier.value
            elif identifier.system == PROFESSIONAL_LICENSE_SYSTEM:
                professional_license = identifier.value
            elif identifier.system == NATIONAL_ID_SYSTEM:
                national_id = identifier.value

        name = practitioner.name[0] if practitioner.name else None
        phone = None
        email = None
        for telecom in practitioner.telecom or []:
            if telecom.system == "phone":
                phone = telecom.value
            elif telecom.system == "email":
                email = telecom.value

        return PractitionerResponse(
            id=practitioner.id,
            keycloak_sub=keycloak_sub,
            professional_license=professional_license,
            national_id=national_id,
            first_name=name.given[0] if name and name.given else None,
            last_name=name.family if name else None,
            title=name.prefix[0] if name and name.prefix else None,
            email=email,
            phone=phone,
            gender=practitioner.gender,
            active=practitioner.active
        )
```

### 4. Service Layer

Modifier `app/services/identity_service.py`:

```python
from typing import Optional
from app.infrastructure.fhir.client import FHIRClient
from app.infrastructure.fhir.mappers import PatientMapper, PractitionerMapper, KEYCLOAK_SYSTEM, NATIONAL_ID_SYSTEM
from app.infrastructure.keycloak.client import KeycloakAdminClient
from app.domain.models import PatientCreate, PatientResponse, PractitionerCreate, PractitionerResponse
from app.domain.exceptions import DuplicateIdentityError, IdentityNotFoundError

class IdentityService:
    def __init__(self, fhir_client: FHIRClient, keycloak_client: KeycloakAdminClient):
        self.fhir = fhir_client
        self.keycloak = keycloak_client

    async def create_patient(self, data: PatientCreate) -> PatientResponse:
        # 1. Vérifier doublons par national_id
        if data.national_id:
            existing = await self.fhir.search_patient_by_identifier(NATIONAL_ID_SYSTEM, data.national_id)
            if existing:
                raise DuplicateIdentityError(f"Patient with national_id {data.national_id} already exists")

        # 2. Créer user Keycloak
        keycloak_user_id = await self.keycloak.create_user(
            username=data.email,
            email=data.email,
            first_name=data.first_name,
            last_name=data.last_name,
            attributes={"national_id": data.national_id, "phone": data.phone}
        )
        await self.keycloak.assign_role(keycloak_user_id, "patient")

        # 3. Créer Patient FHIR
        fhir_patient = PatientMapper.to_fhir(data, keycloak_user_id)
        created_patient = await self.fhir.create_patient(fhir_patient)

        # 4. Publier événement
        # await self.event_publisher.publish("identity.patient.created", {...})

        return PatientMapper.to_domain(created_patient)

    async def get_patient_by_keycloak_sub(self, keycloak_sub: str) -> Optional[PatientResponse]:
        patient = await self.fhir.search_patient_by_identifier(KEYCLOAK_SYSTEM, keycloak_sub)
        if not patient:
            return None
        return PatientMapper.to_domain(patient)

    async def get_patient(self, patient_id: str) -> PatientResponse:
        patient = await self.fhir.get_patient(patient_id)
        if not patient:
            raise IdentityNotFoundError(f"Patient {patient_id} not found")
        return PatientMapper.to_domain(patient)

    async def create_practitioner(self, data: PractitionerCreate) -> PractitionerResponse:
        # 1. Vérifier doublons par professional_license
        if data.professional_license:
            existing = await self.fhir.search_practitioner_by_identifier(
                "http://senegal.gov.sn/professional-license",
                data.professional_license
            )
            if existing:
                raise DuplicateIdentityError(f"Practitioner with license {data.professional_license} already exists")

        # 2. Créer user Keycloak
        keycloak_user_id = await self.keycloak.create_user(
            username=data.email,
            email=data.email,
            first_name=data.first_name,
            last_name=data.last_name,
            attributes={
                "professional_license": data.professional_license,
                "specialty": data.specialty
            }
        )
        await self.keycloak.assign_role(keycloak_user_id, "professional")

        # 3. Créer Practitioner FHIR
        fhir_practitioner = PractitionerMapper.to_fhir(data, keycloak_user_id)
        created_practitioner = await self.fhir.create_practitioner(fhir_practitioner)

        return PractitionerMapper.to_domain(created_practitioner)
```

### 5. Modèles Domain (Pydantic)

Mettre à jour `app/domain/models.py`:

```python
from typing import Optional
from datetime import date
from pydantic import BaseModel, EmailStr

class PatientCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone: Optional[str] = None
    national_id: Optional[str] = None
    gender: Optional[str] = None  # male | female | other | unknown
    birth_date: Optional[date] = None
    city: Optional[str] = None

class PatientResponse(BaseModel):
    id: str  # FHIR Resource ID
    keycloak_sub: Optional[str] = None
    national_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None
    active: Optional[bool] = True

class PractitionerCreate(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    title: Optional[str] = None  # Dr., Pr., etc.
    phone: Optional[str] = None
    national_id: Optional[str] = None
    professional_license: str
    specialty: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[date] = None

class PractitionerResponse(BaseModel):
    id: str  # FHIR Resource ID
    keycloak_sub: Optional[str] = None
    professional_license: Optional[str] = None
    national_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None
    active: Optional[bool] = True
```

### 6. Supprimer Tables SQLAlchemy

Supprimer ou archiver:
- `app/models/patient.py` (table patients)
- `app/models/practitioner.py` (table practitioners)
- Migrations Alembic associées

Conserver:
- Tables de liaison/audit locales si nécessaires
- Table de cache de doublons détectés

### 7. Variables d'Environnement

Ajouter dans `.env`:

```bash
AFRICARE_FHIR_BASE_URL=http://hapi-fhir:8080/fhir
AFRICARE_FHIR_TIMEOUT=30
```

### 8. Tests

Créer `tests/integration/test_fhir_client.py`:

```python
import pytest
from app.infrastructure.fhir.client import FHIRClient, FHIRSettings
from fhir.resources.patient import Patient

@pytest.mark.asyncio
async def test_create_and_get_patient():
    settings = FHIRSettings(fhir_base_url="http://localhost:8080/fhir")
    client = FHIRClient(settings)

    patient = Patient(
        identifier=[{"system": "http://test", "value": "test-123"}],
        name=[{"family": "Test", "given": ["User"]}],
        active=True
    )

    created = await client.create_patient(patient)
    assert created.id is not None

    fetched = await client.get_patient(created.id)
    assert fetched.name[0].family == "Test"

    await client.close()
```

## Fichiers à Supprimer

- `app/models/patient.py`
- `app/models/practitioner.py`
- `app/repositories/patient_repository.py`
- `app/repositories/practitioner_repository.py`
- Migrations Alembic pour tables patients/practitioners

## Fichiers à Créer

- `app/infrastructure/fhir/__init__.py`
- `app/infrastructure/fhir/client.py`
- `app/infrastructure/fhir/mappers.py`
- `tests/integration/test_fhir_client.py`

## Fichiers à Modifier

- `app/services/identity_service.py`
- `app/domain/models.py`
- `app/api/routes/patients.py`
- `app/api/routes/practitioners.py`
- `app/core/dependencies.py` (injection FHIRClient)
- `pyproject.toml` ou `requirements.txt`
