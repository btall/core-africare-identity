---
name: create-event
description: Crée un système de publication/souscription d'événements Redis Pub/Sub ou Azure Event Hub
---

# Créer un Événement AfriCare

Cette commande génère le code pour publier et souscrire à des événements dans l'architecture événementielle AfriCare. Supporte Redis Pub/Sub (MVP) et Azure Event Hub (production).

## Utilisation

```
/create-event <nom_event> [type: domain|audit|notification]
```

**Exemples:**
- `/create-event patient.created domain` - Événement domaine création patient
- `/create-event access.logged audit` - Événement audit RGPD
- `/create-event appointment.reminder notification` - Notification rendez-vous

## Convention de Nommage

Pattern: `{service_slug}.{entity}.{action}`

| Service | Entity | Actions |
|---------|--------|---------|
| `identity` | `patient`, `professional` | `created`, `updated`, `deleted`, `soft_deleted`, `anonymized` |
| `audit` | `access`, `user_action` | `logged` |
| `notification` | `sms`, `email`, `push` | `sent`, `failed`, `delivered` |

**Exemples:**
- `identity.patient.created`
- `identity.professional.soft_deleted`
- `audit.access.logged`

## Template Publication

### Publication Simple

```python
from datetime import UTC, datetime
from app.core.events import publish

# Publication événement domaine
await publish("identity.patient.created", {
    "patient_id": patient.id,
    "keycloak_user_id": patient.keycloak_user_id,
    "timestamp": datetime.now(UTC).isoformat(),
})
```

### Publication avec Schéma Pydantic

```python
from pydantic import BaseModel
from datetime import datetime
from app.core.events import publish


class PatientCreatedEvent(BaseModel):
    """Événement de création d'un patient."""
    patient_id: int
    keycloak_user_id: str
    email: str
    timestamp: str
    created_by: str


# Publication typée
event = PatientCreatedEvent(
    patient_id=patient.id,
    keycloak_user_id=patient.keycloak_user_id,
    email=patient.email,
    timestamp=datetime.now(UTC).isoformat(),
    created_by=current_user.sub,
)

await publish("identity.patient.created", event)
```

### Événement Audit RGPD (Obligatoire)

```python
from datetime import UTC, datetime
from fastapi import Request
from app.core.events import publish

async def audit_access(
    request: Request,
    event_type: str,
    resource_type: str,
    resource_id: int,
    resource_owner_id: str,
    audit_data: dict,  # Retourné par verify_access()
) -> None:
    """Publie un événement d'audit RGPD."""
    await publish("audit.access", {
        "event_type": event_type,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_owner_id": resource_owner_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent"),
        **audit_data,  # accessed_by, access_reason
    })
```

## Template Souscription

### Handler d'Événement

**Fichier**: `app/services/event_service.py`

```python
"""Handlers d'événements pour le service identity."""

import logging
from app.core.events import subscribe

logger = logging.getLogger(__name__)


@subscribe("keycloak.user.REGISTER")
async def handle_user_registration(payload: dict) -> None:
    """
    Traite les événements d'inscription utilisateur depuis Keycloak.

    Args:
        payload: Données de l'événement
            - userId: UUID Keycloak
            - email: Adresse email
            - firstName: Prénom
            - lastName: Nom
            - realmId: Realm Keycloak
    """
    logger.info("Received user registration event", extra={"payload": payload})

    user_id = payload.get("userId")
    if not user_id:
        logger.warning("Registration event missing userId")
        return

    # Logique métier
    # ...

    logger.info(f"Processed registration for user {user_id}")


@subscribe("identity.professional.soft_deleted")
async def handle_professional_soft_delete(payload: dict) -> None:
    """
    Traite les événements de suppression douce des professionnels.

    Args:
        payload: Données de l'événement
            - professional_id: ID du professionnel
            - keycloak_user_id: UUID Keycloak
            - soft_deleted_at: Date de suppression
            - grace_period_end: Fin de la période de grâce
    """
    logger.info("Professional soft deleted", extra={"payload": payload})

    professional_id = payload.get("professional_id")

    # Notifier les services dépendants
    # Ex: apps-africare-appointment-scheduling pour réassignation
```

### Enregistrement au Démarrage

**Dans** `app/main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.core.events import start_consumer, stop_consumer
from app.services import event_service  # Import pour enregistrer les handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan manager pour démarrage/arrêt des consumers."""
    # Démarrage
    await start_consumer()

    yield

    # Arrêt
    await stop_consumer()


app = FastAPI(lifespan=lifespan)
```

## Types d'Événements

### 1. Événements Domaine (Domain Events)

Actions métier significatives:

```python
# Création
await publish("identity.patient.created", {
    "patient_id": id,
    "timestamp": now,
})

# Mise à jour
await publish("identity.professional.updated", {
    "professional_id": id,
    "updated_fields": ["email", "phone"],
    "timestamp": now,
})

# Suppression
await publish("identity.patient.soft_deleted", {
    "patient_id": id,
    "deletion_reason": "user_request",
    "grace_period_end": grace_end,
    "timestamp": now,
})
```

### 2. Événements Audit (RGPD)

Traçabilité des accès:

```python
await publish("audit.access", {
    "event_type": "patient_record_accessed",
    "resource_type": "patient",
    "resource_id": patient_id,
    "resource_owner_id": patient.keycloak_user_id,
    "accessed_by": current_user.sub,  # UUID uniquement (minimisation)
    "access_reason": "owner",  # ou "admin_supervision"
    "ip_address": request.client.host,
    "user_agent": request.headers.get("user-agent"),
    "timestamp": now,
})
```

### 3. Événements Notification

Déclencheurs de notifications:

```python
await publish("notification.appointment.reminder", {
    "patient_id": patient_id,
    "appointment_id": appointment_id,
    "appointment_datetime": appointment.datetime.isoformat(),
    "professional_name": professional.full_name,
    "channels": ["sms", "email"],
    "template": "appointment_reminder_24h",
    "locale": patient.preferred_language,
})
```

## Schémas d'Événements

**Fichier**: `app/schemas/events.py`

```python
"""Schémas Pydantic pour les événements."""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """Schéma de base pour tous les événements."""
    timestamp: str = Field(..., description="ISO 8601 timestamp")


class PatientCreatedEvent(BaseEvent):
    """Événement création patient."""
    patient_id: int
    keycloak_user_id: str
    email: str
    created_by: str


class ProfessionalSoftDeletedEvent(BaseEvent):
    """Événement suppression douce professionnel."""
    professional_id: int
    keycloak_user_id: str
    soft_deleted_at: str
    anonymization_scheduled_at: str
    grace_period_days: int = 7
    deletion_reason: Literal[
        "user_request",
        "admin_termination",
        "professional_revocation",
        "gdpr_compliance",
        "prolonged_inactivity",
    ]


class AuditAccessEvent(BaseEvent):
    """Événement audit RGPD."""
    event_type: str
    resource_type: str
    resource_id: int
    resource_owner_id: str
    accessed_by: str
    access_reason: Literal["owner", "admin_supervision"]
    ip_address: str
    user_agent: Optional[str] = None
```

## Checklist

- [ ] Définir le schéma d'événement dans `app/schemas/events.py`
- [ ] Ajouter la publication dans le code métier
- [ ] Créer le handler de souscription si nécessaire
- [ ] Documenter l'événement dans `docs/events.md`
- [ ] Ajouter les tests pour publish/subscribe
- [ ] Exécuter `make lint` et `make test`

## Ressources

- **Configuration**: Voir `app/core/events.py`
- **Documentation**: Voir `docs/events.md`
- **Tests**: Voir `tests/unit/test_events.py`
