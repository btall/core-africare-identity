# Service Layer Orchestration

Ce document décrit le pattern d'orchestration entre HAPI FHIR et PostgreSQL.

## Pattern d'Orchestration

```
┌─────────────────────────────────────────────────────────────┐
│                     Service Layer                            │
├─────────────────────────────────────────────────────────────┤
│  1. Mapper Pydantic → FHIR                                   │
│  2. Créer/Modifier dans HAPI FHIR                           │
│  3. Créer/Modifier métadonnées GDPR dans PostgreSQL         │
│  4. Mapper FHIR + GDPR → Pydantic Response                  │
│  5. Publier événement                                        │
└─────────────────────────────────────────────────────────────┘
```

## Service Patient

**Fichier**: `app/services/patient_service.py`

```python
"""Service patient avec orchestration FHIR + PostgreSQL."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish
from app.infrastructure.fhir.client import fhir_client
from app.infrastructure.fhir.mappers.patient_mapper import PatientMapper
from app.models.gdpr_metadata import PatientGdprMetadata
from app.schemas.patient import PatientCreate, PatientResponse, PatientUpdate

logger = logging.getLogger(__name__)


async def create_patient(
    db: AsyncSession,
    data: PatientCreate,
    keycloak_user_id: str,
) -> PatientResponse:
    """
    Crée un patient dans HAPI FHIR + métadonnées GDPR.

    Workflow:
    1. Mapper vers FHIR
    2. Créer dans HAPI FHIR (source de vérité)
    3. Créer métadonnées GDPR locales
    4. Publier événement
    5. Retourner réponse avec ID local
    """
    logger.info(f"Creating patient for Keycloak user {keycloak_user_id}")

    # 1. Mapper vers FHIR
    fhir_patient = PatientMapper.to_fhir(data, keycloak_user_id)

    # 2. Créer dans HAPI FHIR
    created_fhir = await fhir_client.create(fhir_patient)
    logger.info(f"Created FHIR Patient: {created_fhir.id}")

    # 3. Créer métadonnées GDPR
    gdpr = PatientGdprMetadata(
        fhir_resource_id=created_fhir.id,
        keycloak_user_id=keycloak_user_id,
        is_verified=False,
    )
    db.add(gdpr)
    await db.commit()
    await db.refresh(gdpr)

    # 4. Publier événement
    await publish("identity.patient.created", {
        "patient_id": gdpr.id,
        "fhir_resource_id": created_fhir.id,
        "keycloak_user_id": keycloak_user_id,
        "timestamp": datetime.now(UTC).isoformat(),
    })

    # 5. Retourner avec ID local
    return PatientMapper.from_fhir(
        created_fhir,
        local_id=gdpr.id,
        gdpr_metadata={
            "is_verified": gdpr.is_verified,
            "created_at": gdpr.created_at,
            "updated_at": gdpr.updated_at,
        },
    )


async def get_patient(
    db: AsyncSession,
    patient_id: int,
) -> PatientResponse | None:
    """
    Récupère un patient par ID local.

    1. Chercher métadonnées GDPR locales
    2. Si trouvé, récupérer Patient FHIR
    3. Fusionner et retourner
    """
    # 1. Chercher métadonnées GDPR
    result = await db.execute(
        select(PatientGdprMetadata).where(PatientGdprMetadata.id == patient_id)
    )
    gdpr = result.scalar_one_or_none()

    if not gdpr:
        return None

    # 2. Récupérer FHIR Patient
    from fhir.resources.patient import Patient
    fhir_patient = await fhir_client.read(Patient, gdpr.fhir_resource_id)

    if not fhir_patient:
        logger.warning(f"FHIR Patient {gdpr.fhir_resource_id} not found")
        return None

    # 3. Fusionner et retourner
    return PatientMapper.from_fhir(
        fhir_patient,
        local_id=gdpr.id,
        gdpr_metadata={
            "is_verified": gdpr.is_verified,
            "under_investigation": gdpr.under_investigation,
            "soft_deleted_at": gdpr.soft_deleted_at,
            "anonymized_at": gdpr.anonymized_at,
            "created_at": gdpr.created_at,
            "updated_at": gdpr.updated_at,
        },
    )


async def get_patient_by_keycloak_id(
    db: AsyncSession,
    keycloak_user_id: str,
) -> PatientResponse | None:
    """Récupère un patient par Keycloak ID."""
    result = await db.execute(
        select(PatientGdprMetadata).where(
            PatientGdprMetadata.keycloak_user_id == keycloak_user_id
        )
    )
    gdpr = result.scalar_one_or_none()

    if not gdpr:
        return None

    return await get_patient(db, gdpr.id)


async def update_patient(
    db: AsyncSession,
    patient_id: int,
    data: PatientUpdate,
    keycloak_user_id: str,
) -> PatientResponse | None:
    """
    Met à jour un patient.

    1. Récupérer métadonnées GDPR + FHIR
    2. Appliquer modifications au FHIR Patient
    3. Update dans HAPI FHIR
    4. Update métadonnées locales si nécessaire
    5. Publier événement
    """
    # 1. Récupérer
    result = await db.execute(
        select(PatientGdprMetadata).where(PatientGdprMetadata.id == patient_id)
    )
    gdpr = result.scalar_one_or_none()

    if not gdpr:
        return None

    from fhir.resources.patient import Patient
    fhir_patient = await fhir_client.read(Patient, gdpr.fhir_resource_id)

    if not fhir_patient:
        return None

    # 2. Appliquer modifications
    update_dict = data.model_dump(exclude_unset=True)

    # Mapper les champs Pydantic vers FHIR
    if "first_name" in update_dict or "last_name" in update_dict:
        if fhir_patient.name:
            name = fhir_patient.name[0]
            if "first_name" in update_dict:
                name.given = [update_dict["first_name"]]
            if "last_name" in update_dict:
                name.family = update_dict["last_name"]

    if "email" in update_dict or "phone" in update_dict:
        telecoms = fhir_patient.telecom or []
        for telecom in telecoms:
            if telecom.system == "email" and "email" in update_dict:
                telecom.value = update_dict["email"]
            if telecom.system == "phone" and "phone" in update_dict:
                telecom.value = update_dict["phone"]

    if "gender" in update_dict:
        fhir_patient.gender = update_dict["gender"]

    if "date_of_birth" in update_dict:
        fhir_patient.birthDate = update_dict["date_of_birth"].isoformat()

    # 3. Update HAPI FHIR
    updated_fhir = await fhir_client.update(fhir_patient)

    # 4. Update métadonnées locales
    gdpr.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(gdpr)

    # 5. Publier événement
    await publish("identity.patient.updated", {
        "patient_id": gdpr.id,
        "fhir_resource_id": updated_fhir.id,
        "updated_fields": list(update_dict.keys()),
        "timestamp": datetime.now(UTC).isoformat(),
    })

    return PatientMapper.from_fhir(
        updated_fhir,
        local_id=gdpr.id,
        gdpr_metadata={
            "is_verified": gdpr.is_verified,
            "created_at": gdpr.created_at,
            "updated_at": gdpr.updated_at,
        },
    )


async def soft_delete_patient(
    db: AsyncSession,
    patient_id: int,
    deletion_reason: str,
    keycloak_user_id: str,
) -> bool:
    """
    Suppression douce d'un patient (période de grâce 7 jours).

    1. Vérifier under_investigation
    2. Générer correlation_hash
    3. Marquer soft_deleted_at
    4. Désactiver dans FHIR (active=false)
    5. Publier événement
    """
    result = await db.execute(
        select(PatientGdprMetadata).where(PatientGdprMetadata.id == patient_id)
    )
    gdpr = result.scalar_one_or_none()

    if not gdpr:
        return False

    # 1. Vérifier blocage
    if gdpr.under_investigation:
        raise ValueError(f"Patient {patient_id} under investigation")

    # 2. Générer hash si absent
    if not gdpr.correlation_hash:
        import hashlib
        from app.core.config import settings
        salt = getattr(settings, "CORRELATION_HASH_SALT", "africare-identity-salt-v1")

        # Récupérer email depuis FHIR
        from fhir.resources.patient import Patient
        fhir_patient = await fhir_client.read(Patient, gdpr.fhir_resource_id)
        email = ""
        if fhir_patient and fhir_patient.telecom:
            for t in fhir_patient.telecom:
                if t.system == "email":
                    email = t.value
                    break

        hash_input = f"{email}|{patient_id}|{salt}"
        gdpr.correlation_hash = hashlib.sha256(hash_input.encode()).hexdigest()

    # 3. Marquer suppression
    now = datetime.now(UTC)
    gdpr.soft_deleted_at = now
    gdpr.deletion_reason = deletion_reason
    await db.commit()

    # 4. Désactiver dans FHIR
    from fhir.resources.patient import Patient
    fhir_patient = await fhir_client.read(Patient, gdpr.fhir_resource_id)
    if fhir_patient:
        fhir_patient.active = False
        await fhir_client.update(fhir_patient)

    # 5. Publier événement
    from datetime import timedelta
    grace_period_end = now + timedelta(days=7)

    await publish("identity.patient.soft_deleted", {
        "patient_id": patient_id,
        "fhir_resource_id": gdpr.fhir_resource_id,
        "soft_deleted_at": now.isoformat(),
        "grace_period_end": grace_period_end.isoformat(),
        "deletion_reason": deletion_reason,
    })

    return True
```

## Injection de Dépendances

**Fichier**: `app/core/dependencies.py`

```python
"""Dépendances FastAPI."""

from app.infrastructure.fhir.client import fhir_client


def get_fhir_client():
    """Retourne le client FHIR singleton."""
    return fhir_client
```

## Utilisation dans les Endpoints

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import get_current_user, User
from app.services import patient_service
from app.schemas.patient import PatientCreate, PatientResponse

router = APIRouter()


@router.post("/", response_model=PatientResponse)
async def create_patient(
    data: PatientCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await patient_service.create_patient(
        db=db,
        data=data,
        keycloak_user_id=current_user.sub,
    )


@router.get("/{patient_id}", response_model=PatientResponse)
async def get_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    patient = await patient_service.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")

    # Vérification accès
    current_user.verify_access(patient.keycloak_user_id)

    return patient
```

## Gestion des Erreurs

```python
from fastapi import HTTPException
from app.infrastructure.fhir.exceptions import FHIRError, FHIRConnectionError


@router.post("/")
async def create_patient(...):
    try:
        return await patient_service.create_patient(...)
    except FHIRConnectionError:
        raise HTTPException(503, "FHIR server unavailable")
    except FHIRError as e:
        raise HTTPException(500, f"FHIR error: {e.message}")
```
