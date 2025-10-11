"""
Endpoints d'exemple pour core-africare-identity.

Utilise SQLAlchemy 2.0 avec PostgreSQL pour les opérations CRUD.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_session
from app.models.example import Example, ExampleCreate, ExampleUpdate, ExampleResponse
from app.core.events import publish

router = APIRouter()


@router.post("/", response_model=ExampleResponse)
async def create_example(
    example_data: ExampleCreate,
    db: AsyncSession = Depends(get_session)
) -> ExampleResponse:
    """Crée un nouvel exemple (PostgreSQL)."""
    example = Example(**example_data.model_dump())

    db.add(example)
    await db.commit()
    await db.refresh(example)

    # Publier l'événement
    await publish("identity.example.created", {
        "example_id": example.id,
        "name": example.name,
        "timestamp": example.created_at.isoformat()
    })

    return ExampleResponse.model_validate(example)


@router.get("/{example_id}", response_model=ExampleResponse)
async def get_example(
    example_id: int,
    db: AsyncSession = Depends(get_session)
) -> ExampleResponse:
    """Récupère un exemple par son ID (PostgreSQL)."""
    example = await db.get(Example, example_id)
    if not example:
        raise HTTPException(status_code=404, detail="Example not found")

    return ExampleResponse.model_validate(example)


@router.get("/", response_model=List[ExampleResponse])
async def list_examples(
    limit: int = 100,
    db: AsyncSession = Depends(get_session)
) -> List[ExampleResponse]:
    """Liste tous les exemples (PostgreSQL)."""
    result = await db.execute(select(Example).limit(limit))
    examples = result.scalars().all()

    return [ExampleResponse.model_validate(example) for example in examples]


@router.put("/{example_id}", response_model=ExampleResponse)
async def update_example(
    example_id: int,
    example_data: ExampleUpdate,
    db: AsyncSession = Depends(get_session)
) -> ExampleResponse:
    """Met à jour un exemple (PostgreSQL)."""
    example = await db.get(Example, example_id)
    if not example:
        raise HTTPException(status_code=404, detail="Example not found")

    # Mettre à jour les champs non-null
    update_data = example_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(example, field, value)

    db.add(example)
    await db.commit()
    await db.refresh(example)

    # Publier l'événement
    await publish("identity.example.updated", {
        "example_id": example.id,
        "name": example.name,
        "timestamp": example.updated_at.isoformat() if example.updated_at else None
    })

    return ExampleResponse.model_validate(example)


@router.delete("/{example_id}")
async def delete_example(
    example_id: int,
    db: AsyncSession = Depends(get_session)
):
    """Supprime un exemple (PostgreSQL)."""
    example = await db.get(Example, example_id)
    if not example:
        raise HTTPException(status_code=404, detail="Example not found")

    await db.delete(example)
    await db.commit()

    # Publier l'événement
    await publish("identity.example.deleted", {
        "example_id": example_id,
        "timestamp": datetime.now().isoformat()
    })

    return {"message": "Example deleted successfully"}
