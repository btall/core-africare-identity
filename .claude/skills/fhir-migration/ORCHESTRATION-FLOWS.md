# Flux d'Orchestration Keycloak ↔ FHIR

Ce document décrit les flux d'orchestration entre Keycloak et HAPI FHIR gérés par core-africare-identity.

## Principe de Séparation

| Domaine | Keycloak | FHIR |
|---------|----------|------|
| Authentification | ✓ | |
| Sessions, tokens | ✓ | |
| Appartenance organisationnelle | ✓ | |
| Rôles techniques (RBAC) | ✓ | |
| Données démographiques | | ✓ |
| Données cliniques | | ✓ |
| Consentements | | ✓ |
| Qualifications professionnelles | | ✓ |
| Traçabilité accès/modifications | | ✓ |

**Règle**: Keycloak gère "qui peut entrer et avec quelles clés". FHIR gère "quelles données existent et qui peut les voir".

## Flow 1: Création Professionnel

```
┌─────────┐     ┌──────────┐     ┌─────────────────────┐     ┌──────────┐
│  Admin  │     │ Keycloak │     │ core-africare-      │     │ HAPI     │
│ Portal  │     │          │     │ identity            │     │ FHIR     │
└────┬────┘     └────┬─────┘     └──────────┬──────────┘     └────┬─────┘
     │               │                      │                     │
     │ 1. Create User│                      │                     │
     │──────────────>│                      │                     │
     │               │                      │                     │
     │ User created  │                      │                     │
     │<──────────────│                      │                     │
     │ (sub: uuid)   │                      │                     │
     │               │                      │                     │
     │ 2. POST /practitioners              │                     │
     │────────────────────────────────────>│                     │
     │ {keycloak_sub, name, license...}    │                     │
     │               │                      │                     │
     │               │                      │ 3. POST /Practitioner
     │               │                      │────────────────────>│
     │               │                      │                     │
     │               │                      │ Practitioner/pract-042
     │               │                      │<────────────────────│
     │               │                      │                     │
     │               │ 4. PATCH User       │                     │
     │               │<─────────────────────│                     │
     │               │ fhir_practitioner_id │                     │
     │               │                      │                     │
     │               │                      │ 5. POST /PractitionerRole
     │               │                      │────────────────────>│
     │               │                      │ {practitioner, org} │
     │               │                      │                     │
     │               │ 6. Add to Org       │                     │
     │               │<─────────────────────│                     │
     │               │                      │                     │
     │ 7. Practitioner créé                │                     │
     │<────────────────────────────────────│                     │
```

### Implémentation

**Fichier**: `app/services/professional_service.py`

```python
"""Service de création de professionnels avec orchestration Keycloak + FHIR."""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish
from app.infrastructure.fhir.client import fhir_client
from app.infrastructure.fhir.mappers.professional_mapper import ProfessionalMapper
from app.infrastructure.keycloak.client import keycloak_admin
from app.models.gdpr_metadata import ProfessionalGdprMetadata
from app.schemas.professional import ProfessionalCreate, ProfessionalResponse

logger = logging.getLogger(__name__)


async def create_professional(
    db: AsyncSession,
    data: ProfessionalCreate,
    organization_id: str,
) -> ProfessionalResponse:
    """
    Crée un professionnel avec orchestration Keycloak + FHIR.

    Workflow:
    1. Créer User dans Keycloak
    2. Créer Practitioner dans HAPI FHIR
    3. Lier User Keycloak → Practitioner FHIR
    4. Créer PractitionerRole (lien org)
    5. Ajouter User à l'Organization Keycloak
    6. Créer métadonnées GDPR locales
    """
    logger.info(f"Creating professional for org {organization_id}")

    # 1. Créer User Keycloak
    keycloak_user_id = await keycloak_admin.create_user(
        email=data.email,
        first_name=data.first_name,
        last_name=data.last_name,
        enabled=True,
        attributes={
            "phone": data.phone,
            "professional_type": data.professional_type,
        },
    )
    logger.info(f"Created Keycloak user: {keycloak_user_id}")

    # Assigner rôle "professional"
    await keycloak_admin.assign_realm_role(keycloak_user_id, "professional")

    try:
        # 2. Créer Practitioner FHIR
        fhir_practitioner = ProfessionalMapper.to_fhir(data, keycloak_user_id)
        created_fhir = await fhir_client.create(fhir_practitioner)
        logger.info(f"Created FHIR Practitioner: {created_fhir.id}")

        # 3. Lier User → Practitioner
        await keycloak_admin.update_user_attributes(
            keycloak_user_id,
            {"fhir_practitioner_id": created_fhir.id},
        )

        # 4. Créer PractitionerRole
        practitioner_role = await create_practitioner_role(
            practitioner_id=created_fhir.id,
            organization_id=organization_id,
            role_codes=data.role_codes or ["practitioner"],
            specialty=data.specialty,
        )
        logger.info(f"Created PractitionerRole: {practitioner_role.id}")

        # 5. Ajouter à l'Organization Keycloak
        await keycloak_admin.add_user_to_organization(
            keycloak_user_id,
            organization_id,
            roles=data.organization_roles or ["practitioner"],
        )

        # 6. Créer métadonnées GDPR
        gdpr = ProfessionalGdprMetadata(
            fhir_resource_id=created_fhir.id,
            keycloak_user_id=keycloak_user_id,
            is_verified=False,
        )
        db.add(gdpr)
        await db.commit()
        await db.refresh(gdpr)

        # Publier événement
        await publish("identity.professional.created", {
            "professional_id": gdpr.id,
            "fhir_resource_id": created_fhir.id,
            "keycloak_user_id": keycloak_user_id,
            "organization_id": organization_id,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        return ProfessionalMapper.from_fhir(
            created_fhir,
            local_id=gdpr.id,
            gdpr_metadata={
                "is_verified": gdpr.is_verified,
                "created_at": gdpr.created_at,
            },
        )

    except Exception as e:
        # Rollback: supprimer User Keycloak si FHIR échoue
        logger.error(f"Failed to create professional, rolling back: {e}")
        await keycloak_admin.delete_user(keycloak_user_id)
        raise


async def create_practitioner_role(
    practitioner_id: str,
    organization_id: str,
    role_codes: list[str],
    specialty: str | None = None,
) -> "PractitionerRole":
    """Crée un PractitionerRole dans HAPI FHIR."""
    from fhir.resources.practitionerrole import PractitionerRole

    pr = PractitionerRole(
        active=True,
        practitioner={"reference": f"Practitioner/{practitioner_id}"},
        organization={"reference": f"Organization/{organization_id}"},
        code=[
            {
                "coding": [{
                    "system": "https://africare.app/fhir/CodeSystem/practitioner-role",
                    "code": code,
                }]
            }
            for code in role_codes
        ],
    )

    if specialty:
        pr.specialty = [{
            "coding": [{
                "system": "http://snomed.info/sct",
                "display": specialty,
            }],
            "text": specialty,
        }]

    return await fhir_client.create(pr)
```

## Flow 2: Création Patient

```
┌─────────┐     ┌──────────┐     ┌─────────────────────┐     ┌──────────┐
│ Patient │     │ Keycloak │     │ core-africare-      │     │ HAPI     │
│ Portal  │     │          │     │ identity            │     │ FHIR     │
└────┬────┘     └────┬─────┘     └──────────┬──────────┘     └────┬─────┘
     │               │                      │                     │
     │ 1. Self-register                    │                     │
     │──────────────>│                      │                     │
     │               │                      │                     │
     │               │ 2. Event: REGISTER  │                     │
     │               │─────────────────────>│                     │
     │               │                      │                     │
     │               │                      │ 3. POST /Patient    │
     │               │                      │────────────────────>│
     │               │                      │                     │
     │               │                      │ Patient/pat-001     │
     │               │                      │<────────────────────│
     │               │                      │                     │
     │               │ 4. Update attributes│                     │
     │               │<─────────────────────│                     │
     │               │ fhir_patient_id      │                     │
     │               │                      │                     │
     │ 5. Login      │                      │                     │
     │──────────────>│                      │                     │
     │               │                      │                     │
     │ JWT + fhir_id │                      │                     │
     │<──────────────│                      │                     │
```

### Implémentation via Event Handler

**Fichier**: `app/services/event_handlers.py`

```python
"""Event handlers pour synchronisation Keycloak → FHIR."""

import logging
from app.core.events import subscribe
from app.core.database import async_session_maker

logger = logging.getLogger(__name__)


@subscribe("keycloak.user.REGISTER")
async def handle_user_registration(payload: dict) -> None:
    """
    Gère l'inscription d'un nouvel utilisateur depuis Keycloak.

    Crée automatiquement la ressource Patient FHIR correspondante.
    """
    from app.infrastructure.fhir.client import fhir_client
    from app.infrastructure.fhir.mappers.patient_mapper import PatientMapper
    from app.infrastructure.keycloak.client import keycloak_admin
    from app.models.gdpr_metadata import PatientGdprMetadata
    from app.schemas.patient import PatientCreate

    logger.info("Received REGISTER event", extra={"payload": payload})

    keycloak_user_id = payload.get("userId")
    if not keycloak_user_id:
        logger.warning("REGISTER event missing userId")
        return

    # Vérifier rôle (patient vs professional)
    roles = payload.get("realmRoles", [])
    if "professional" in roles:
        logger.info(f"User {keycloak_user_id} is professional, skipping patient creation")
        return

    # Extraire données utilisateur
    email = payload.get("email")
    first_name = payload.get("firstName", "")
    last_name = payload.get("lastName", "")

    # Créer PatientCreate depuis event
    patient_data = PatientCreate(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=payload.get("attributes", {}).get("phone"),
        preferred_language="fr",
    )

    async with async_session_maker() as db:
        # Créer Patient FHIR
        fhir_patient = PatientMapper.to_fhir(patient_data, keycloak_user_id)
        created_fhir = await fhir_client.create(fhir_patient)

        logger.info(f"Created FHIR Patient: {created_fhir.id}")

        # Mettre à jour attribut Keycloak
        await keycloak_admin.update_user_attributes(
            keycloak_user_id,
            {"fhir_patient_id": created_fhir.id},
        )

        # Créer métadonnées GDPR
        gdpr = PatientGdprMetadata(
            fhir_resource_id=created_fhir.id,
            keycloak_user_id=keycloak_user_id,
            is_verified=False,
        )
        db.add(gdpr)
        await db.commit()

        logger.info(f"Patient registration complete for {keycloak_user_id}")
```

## Flow 3: Changement d'Organisation Active

Quand un praticien multi-établissements change son organisation active:

```python
# JWT claims après switch d'organisation
{
    "sub": "uuid-keycloak-user",
    "fhir_practitioner_id": "pract-042",
    "organizations": [
        {"id": "org-chu-fann", "roles": ["practitioner", "department-head"]},
        {"id": "org-clinique-abc", "roles": ["consultant"]},
        {"id": "org-cabinet-dr-sall", "roles": ["owner"]},
    ],
    "active_org": "org-clinique-abc"  # Nouvelle organisation active
}
```

**Impact sur les requêtes FHIR**:

```python
# core-africare-ehr injecte le header X-Organization-Id
async def proxy_fhir_request(request: Request, current_user: User):
    headers = {
        "X-Organization-Id": current_user.active_org,
        "X-Practitioner-Id": current_user.fhir_practitioner_id,
    }
    # Forward to HAPI FHIR
```

## Flow 4: Accès Données avec Consent

```
┌─────────┐     ┌─────────┐     ┌──────────┐     ┌──────────────────────┐
│ Dr.Sall │     │ Provider│     │ core-    │     │ HAPI FHIR            │
│ CHU Fann│     │ Portal  │     │ ehr      │     │ + ConsentInterceptor │
└────┬────┘     └────┬────┘     └────┬─────┘     └──────────┬───────────┘
     │               │               │                      │
     │ Voir Patient X│               │                      │
     │──────────────>│               │                      │
     │               │               │                      │
     │               │ GET Patient/X/$everything            │
     │               │ JWT: active_org=chu-fann             │
     │               │──────────────>│                      │
     │               │               │                      │
     │               │               │ GET Patient/X/$everything
     │               │               │ X-Organization-Id: chu-fann
     │               │               │─────────────────────>│
     │               │               │                      │
     │               │               │      ┌───────────────┤
     │               │               │      │ Check Consent │
     │               │               │      │ Patient X     │
     │               │               │      │ → permit CHU  │
     │               │               │      │   Fann        │
     │               │               │      └───────────────┤
     │               │               │                      │
     │               │               │ Bundle (filtré)      │
     │               │               │<─────────────────────│
     │               │               │                      │
     │               │ Bundle        │                      │
     │               │<──────────────│                      │
     │               │               │                      │
     │ Dossier affiché               │                      │
     │<──────────────│               │                      │
```

## Flow 5: Création lors d'une Consultation

Quand un médecin crée une observation, HAPI FHIR génère automatiquement:
- `Provenance` avec `onBehalfOf` = Organization active
- `AuditEvent` pour traçabilité

```python
# Requête originale
POST /Observation
X-Organization-Id: org-chu-fann
X-Practitioner-Id: pract-042
{
    "resourceType": "Observation",
    "subject": {"reference": "Patient/pat-001"},
    "code": {...},
    "valueQuantity": {...}
}

# HAPI crée automatiquement Provenance
{
    "resourceType": "Provenance",
    "target": [{"reference": "Observation/obs-new"}],
    "agent": [{
        "who": {"reference": "Practitioner/pract-042"},
        "onBehalfOf": {"reference": "Organization/org-chu-fann"}
    }]
}
```

## Responsabilités par Microservice

| Microservice | Keycloak | FHIR |
|--------------|----------|------|
| **core-africare-identity** | CRUD users, org membership | CRUD Patient, Practitioner, PractitionerRole |
| core-africare-ehr | Validation JWT, extraction org_id | Proxy HAPI, CRUD ressources cliniques |
| core-africare-consent-management | Aucun | CRUD Consent |
| core-africare-audit-log | Aucun | Lecture AuditEvent, archivage |
| apps-africare-provider-portal | Login, token refresh, switch org | Lecture/écriture via core-africare-ehr |
| apps-africare-patient-portal | Login, token refresh | Lecture propres données, CRUD propres Consent |
| apps-africare-admin-portal | CRUD organizations, users, roles | CRUD Organization, Location |

## Configuration HAPI FHIR

Pour activer la génération automatique de Provenance et AuditEvent:

```yaml
# hapi.application.yaml
hapi:
  fhir:
    auto_create_provenance: true
    auto_create_audit_event: true

    # Intercepteurs pour injection organisation
    interceptors:
      - org.africare.fhir.OrganizationContextInterceptor
      - org.africare.fhir.ConsentEnforcementInterceptor
```
