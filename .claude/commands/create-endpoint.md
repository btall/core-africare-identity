---
name: create-endpoint
description: Génère un endpoint FastAPI complet avec validation Pydantic, auth Keycloak, audit RGPD et OpenTelemetry
---

# Créer un Endpoint FastAPI AfriCare

Cette commande génère un endpoint FastAPI complet suivant les patterns et conventions du projet AfriCare. Elle crée automatiquement le code avec validation Pydantic, authentification Keycloak, audit RGPD, et instrumentation OpenTelemetry.

## Utilisation

```
/create-endpoint <nom_resource> <methode_http> [description]
```

**Exemples:**
- `/create-endpoint patient POST` - Créer un patient
- `/create-endpoint professional GET` - Récupérer un professionnel
- `/create-endpoint appointment DELETE` - Supprimer un rendez-vous

## Template Endpoint

### Structure de fichier

**Fichier**: `app/api/v1/endpoints/{resource}.py`

```python
"""Endpoints pour la gestion des {resource}s."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.events import publish
from app.core.security import User, get_current_user
from app.models.{resource} import {Resource}
from app.schemas.{resource} import (
    {Resource}Create,
    {Resource}Response,
    {Resource}Update,
)

router = APIRouter()


@router.post(
    "/",
    response_model={Resource}Response,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un(e) {resource}",
    description="Enregistre un(e) nouveau/nouvelle {resource} dans le système.",
)
async def create_{resource}(
    {resource}_data: {Resource}Create,
    request: Request,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> {Resource}Response:
    """Création d'un(e) nouveau/nouvelle {resource}."""
    # Vérification des droits d'accès
    audit_data = current_user.verify_access(current_user.sub)

    # Création de l'entité
    {resource} = {Resource}(**{resource}_data.model_dump())
    db.add({resource})
    await db.commit()
    await db.refresh({resource})

    # Publication de l'événement
    await publish("identity.{resource}.created", {
        "{resource}_id": {resource}.id,
        "timestamp": datetime.now(UTC).isoformat(),
        **audit_data,
    })

    # Audit RGPD
    await publish("audit.access", {
        "event_type": "{resource}_created",
        "resource_type": "{resource}",
        "resource_id": {resource}.id,
        "timestamp": datetime.now(UTC).isoformat(),
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent"),
        **audit_data,
    })

    return {Resource}Response.model_validate({resource})


@router.get(
    "/{{resource}_id}",
    response_model={Resource}Response,
    summary="Récupérer un(e) {resource}",
    description="Récupère les détails d'un(e) {resource} par son ID.",
)
async def get_{resource}(
    {resource}_id: int,
    request: Request,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> {Resource}Response:
    """Récupération d'un(e) {resource} par ID."""
    result = await db.execute(
        select({Resource}).where({Resource}.id == {resource}_id)
    )
    {resource} = result.scalar_one_or_none()

    if not {resource}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{Resource} {{{resource}_id}} non trouvé(e)",
        )

    # Vérification des droits et audit
    audit_data = current_user.verify_access({resource}.keycloak_user_id)

    await publish("audit.access", {
        "event_type": "{resource}_accessed",
        "resource_type": "{resource}",
        "resource_id": {resource}.id,
        "resource_owner_id": {resource}.keycloak_user_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent"),
        **audit_data,
    })

    return {Resource}Response.model_validate({resource})


@router.put(
    "/{{resource}_id}",
    response_model={Resource}Response,
    summary="Mettre à jour un(e) {resource}",
    description="Met à jour les informations d'un(e) {resource}.",
)
async def update_{resource}(
    {resource}_id: int,
    {resource}_data: {Resource}Update,
    request: Request,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> {Resource}Response:
    """Mise à jour d'un(e) {resource}."""
    result = await db.execute(
        select({Resource}).where({Resource}.id == {resource}_id)
    )
    {resource} = result.scalar_one_or_none()

    if not {resource}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{Resource} {{{resource}_id}} non trouvé(e)",
        )

    # Vérification des droits
    audit_data = current_user.verify_access({resource}.keycloak_user_id)

    # Mise à jour des champs
    update_dict = {resource}_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr({resource}, key, value)

    {resource}.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh({resource})

    # Publication de l'événement
    await publish("identity.{resource}.updated", {
        "{resource}_id": {resource}.id,
        "updated_fields": list(update_dict.keys()),
        "timestamp": datetime.now(UTC).isoformat(),
        **audit_data,
    })

    return {Resource}Response.model_validate({resource})


@router.delete(
    "/{{resource}_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un(e) {resource}",
    description="Supprime un(e) {resource} du système (soft delete).",
)
async def delete_{resource}(
    {resource}_id: int,
    request: Request,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> None:
    """Suppression (soft delete) d'un(e) {resource}."""
    result = await db.execute(
        select({Resource}).where({Resource}.id == {resource}_id)
    )
    {resource} = result.scalar_one_or_none()

    if not {resource}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{Resource} {{{resource}_id}} non trouvé(e)",
        )

    # Vérification des droits
    audit_data = current_user.verify_access({resource}.keycloak_user_id)

    # Soft delete
    {resource}.is_active = False
    {resource}.soft_deleted_at = datetime.now(UTC)
    await db.commit()

    # Publication de l'événement
    await publish("identity.{resource}.deleted", {
        "{resource}_id": {resource}.id,
        "deleted_at": datetime.now(UTC).isoformat(),
        **audit_data,
    })
```

## Intégration Router

**Ajouter dans** `app/api/v1/api.py`:

```python
from app.api.v1.endpoints import {resource}

router.include_router(
    {resource}.router,
    prefix="/{resource}s",
    tags=["{resource}s"],
)
```

## Checklist

- [ ] Créer le fichier endpoint `app/api/v1/endpoints/{resource}.py`
- [ ] Créer/vérifier le modèle `app/models/{resource}.py`
- [ ] Créer/vérifier les schémas `app/schemas/{resource}.py`
- [ ] Intégrer dans `app/api/v1/api.py`
- [ ] Ajouter les tests `tests/unit/test_{resource}_endpoints.py`
- [ ] Exécuter `make lint` et `make test`
- [ ] Documenter les événements dans `docs/events.md`

## Conventions AfriCare

### Nommage
- **Endpoint**: snake_case pour fonctions (`create_patient`)
- **URL**: kebab-case pluriel (`/patients`, `/professionals`)
- **Modèle**: PascalCase singulier (`Patient`, `Professional`)

### Événements
Pattern: `identity.{resource}.{action}`
- `identity.patient.created`
- `identity.professional.updated`
- `identity.appointment.deleted`

### Authentification
Toujours utiliser `Depends(get_current_user)` pour les endpoints protégés.

### Audit RGPD
Toujours publier `audit.access` avec:
- `event_type`
- `resource_type`
- `resource_id`
- `ip_address`
- `user_agent`
- `**audit_data` (en dernier)

## Ressources

- **Patterns**: Voir `CLAUDE.md` section "API Development Patterns"
- **Schémas**: Voir `app/schemas/utils.py` pour annotations réutilisables
- **Sécurité**: Voir `app/core/security.py` pour `verify_access()`
