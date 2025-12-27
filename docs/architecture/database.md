# Gestion de la Base de Données avec SQLAlchemy 2.0 (PostgreSQL)

Ce document explique l'utilisation du module `database.py` qui gère la connexion à la base de données PostgreSQL via **SQLAlchemy 2.0** avec les annotations `Mapped[]`.

## Architecture Globale

Le module `database.py` fournit les composants essentiels pour interagir avec la base de données :

1. **Engine SQLAlchemy 2.0** : Connexion asynchrone à PostgreSQL
2. **AsyncSession** : Sessions de base de données asynchrones
3. **DeclarativeBase** : Classe de base pour tous les modèles ORM
4. **Mapped[]** : Annotations de types modernes pour les colonnes
5. **Alembic** : Migrations configurées pour SQLAlchemy 2.0
## Configuration

La configuration de la base de données est définie dans `app/core/config.py` via la variable d'environnement `SQLALCHEMY_DATABASE_URI` :

```env
# Base de données
SQLALCHEMY_DATABASE_URI=postgresql+asyncpg://core-africare-identity:vd8bveedbnBpMcYr_8qB6A@postgres:5432/core-africare-identity
```

Format typique :

```
postgresql+asyncpg://user:password@host:port/dbname
```

## Code SQLAlchemy 2.0

### DeclarativeBase et Engine

```python
# app/core/database.py
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings


class Base(DeclarativeBase):
    """Base class pour tous les modèles SQLAlchemy."""
    pass


# Engine SQLAlchemy 2.0
engine = create_async_engine(str(settings.SQLALCHEMY_DATABASE_URI), echo=settings.DEBUG)

# Session factory
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Obtient une session de base de données."""
    async with async_session_maker() as session:
        yield session


async def create_db_and_tables():
    """Crée toutes les tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

### Modèles avec Mapped[]

```python
# app/models/example.py
from typing import Optional
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Example(Base):
    """Modèle de table SQLAlchemy pour PostgreSQL."""
    __tablename__ = "examples"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(1000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None, onupdate=func.now())
```

**Schémas Pydantic séparés pour l'API**:

```python
from pydantic import BaseModel, Field


class ExampleBase(BaseModel):
    """Modèle de base partagé pour l'API."""
    name: str = Field(description="Nom de l'exemple")
    description: Optional[str] = Field(default=None, description="Description optionnelle")


class ExampleCreate(ExampleBase):
    """Modèle pour création via API."""
    pass


class ExampleUpdate(BaseModel):
    """Modèle pour mise à jour via API."""
    name: Optional[str] = None
    description: Optional[str] = None


class ExampleResponse(ExampleBase):
    """Modèle de réponse API."""
    id: int
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True
```

## Utilisation dans les Endpoints FastAPI

### Dépendance de Session

```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session

@app.get("/examples/{example_id}")
async def read_example(
    example_id: int,
    db: AsyncSession = Depends(get_session)
):
    example = await db.get(Example, example_id)
    if not example:
        raise HTTPException(status_code=404, detail="Example not found")
    return ExampleResponse.model_validate(example)
```

### Opérations CRUD Asynchrones

#### Création

```python
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.example import Example


async def create_example(
    db: AsyncSession,
    name: str,
    description: str = None
) -> Example:
    example = Example(name=name, description=description)
    db.add(example)
    await db.commit()
    await db.refresh(example)
    return example
```

#### Lecture

```python
from sqlalchemy import select


async def get_example(db: AsyncSession, example_id: int) -> Example | None:
    return await db.get(Example, example_id)


async def get_examples(db: AsyncSession, limit: int = 100):
    result = await db.execute(select(Example).limit(limit))
    return result.scalars().all()
```

#### Mise à jour

```python
async def update_example(
    db: AsyncSession,
    example_id: int,
    name: str = None,
    description: str = None
) -> Example | None:
    example = await db.get(Example, example_id)
    if example:
        if name is not None:
            example.name = name
        if description is not None:
            example.description = description
        db.add(example)
        await db.commit()
        await db.refresh(example)
    return example
```

#### Suppression

```python
async def delete_example(db: AsyncSession, example_id: int) -> bool:
    example = await db.get(Example, example_id)
    if example:
        await db.delete(example)
        await db.commit()
        return True
    return False
```

## Relations SQLAlchemy 2.0

### Relations simples avec Mapped[]

```python
# app/models/user.py
from typing import List, Optional
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    # Relation avec les posts
    posts: Mapped[List["Post"]] = relationship(back_populates="author")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(String(5000))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Relation avec l'auteur
    author: Mapped["User"] = relationship(back_populates="posts")
```

### Utilisation des relations

```python
from sqlalchemy.orm import selectinload


async def get_user_with_posts(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(User)
        .options(selectinload(User.posts))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user:
        return {"user": user, "posts": user.posts}
    return None
```

## Migrations avec Alembic

### Configuration Alembic pour SQLAlchemy 2.0

Le template est déjà configuré pour SQLAlchemy 2.0 dans `alembic/env.py` :

```python
from app.core.database import Base
from app.models import *  # Import tous les modèles

# SQLAlchemy utilise Base.metadata
target_metadata = Base.metadata
```

### Workflow de Migration

```bash
# 1. Créer/modifier des modèles SQLAlchemy dans app/models/
# 2. Importer les modèles dans app/models/__init__.py
# 3. Générer une migration
make migrate MESSAGE="Add example table"

# 4. Vérifier le fichier généré dans alembic/versions/
# 5. Appliquer la migration
make migrate-up
```

## Service Complet - Exemple

### Modèle

```python
# app/models/booking.py
from typing import Optional
from datetime import datetime
from enum import Enum
from sqlalchemy import String, Integer, DateTime, Enum as SQLEnum, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class BookingStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    practitioner_id: Mapped[int] = mapped_column(Integer, index=True)
    patient_id: Mapped[int] = mapped_column(Integer, index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BookingStatus] = mapped_column(
        SQLEnum(BookingStatus),
        default=BookingStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
```

### Service

```python
# app/services/booking_service.py
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.booking import Booking, BookingStatus


class BookingService:
    @staticmethod
    async def create_booking(
        db: AsyncSession,
        practitioner_id: int,
        patient_id: int,
        start_time: datetime,
        end_time: datetime
    ) -> Booking:
        booking = Booking(
            practitioner_id=practitioner_id,
            patient_id=patient_id,
            start_time=start_time,
            end_time=end_time
        )

        db.add(booking)
        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def get_bookings_by_practitioner(
        db: AsyncSession,
        practitioner_id: int
    ) -> list[Booking]:
        result = await db.execute(
            select(Booking).where(Booking.practitioner_id == practitioner_id)
        )
        return result.scalars().all()

    @staticmethod
    async def confirm_booking(
        db: AsyncSession,
        booking_id: int
    ) -> Booking | None:
        booking = await db.get(Booking, booking_id)
        if booking and booking.status == BookingStatus.PENDING:
            booking.status = BookingStatus.CONFIRMED
            db.add(booking)
            await db.commit()
            await db.refresh(booking)
            return booking
        return None
```

### Endpoints

```python
# app/api/v1/endpoints/bookings.py
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.services.booking_service import BookingService
from app.models.booking import Booking
from app.schemas.booking import BookingCreate, BookingResponse

router = APIRouter()


@router.post("/bookings/", response_model=BookingResponse)
async def create_booking(
    booking_data: BookingCreate,
    db: AsyncSession = Depends(get_session)
) -> BookingResponse:
    booking = await BookingService.create_booking(
        db,
        booking_data.practitioner_id,
        booking_data.patient_id,
        booking_data.start_time,
        booking_data.end_time
    )
    return BookingResponse.model_validate(booking)


@router.get("/practitioners/{practitioner_id}/bookings/", response_model=list[BookingResponse])
async def get_practitioner_bookings(
    practitioner_id: int,
    db: AsyncSession = Depends(get_session)
) -> list[BookingResponse]:
    bookings = await BookingService.get_bookings_by_practitioner(db, practitioner_id)
    return [BookingResponse.model_validate(b) for b in bookings]


@router.post("/bookings/{booking_id}/confirm", response_model=BookingResponse)
async def confirm_booking(
    booking_id: int,
    db: AsyncSession = Depends(get_session)
) -> BookingResponse:
    booking = await BookingService.confirm_booking(db, booking_id)
    if not booking:
        raise HTTPException(
            status_code=404,
            detail="Booking not found or cannot be confirmed"
        )
    return BookingResponse.model_validate(booking)
```

## Avantages de SQLAlchemy 2.0

### 1. Type Safety Moderne

- **Mapped[]** : Annotations de types explicites et vérifiables
- **Type hints** : Support complet de mypy et IDE
- **Validation statique** : Détection d'erreurs avant l'exécution

### 2. Async/Await Natif

- **AsyncSession** : Support complet des opérations asynchrones
- **Performance** : Non-bloquant pour les I/O
- **Scalabilité** : Meilleur pour les applications haute performance

### 3. Séparation des Responsabilités

- **ORM models** : Représentation de la base de données
- **Pydantic models** : Validation et sérialisation API
- **Flexibilité** : Modèles API indépendants de la structure DB

### 4. Compatibilité SQLAlchemy

- **Toutes les fonctionnalités** SQLAlchemy 2.0 disponibles
- **Migrations Alembic** : Support complet
- **Relations complexes** : Jointures, eager loading, etc.

## Bonnes Pratiques

### 1. Structure des Modèles

```python
# Utiliser Mapped[] pour toutes les colonnes
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
```

### 2. Sessions Asynchrones

```python
# Toujours utiliser async/await avec AsyncSession
async def get_user(db: AsyncSession, user_id: int):
    user = await db.get(User, user_id)
    return user
```

### 3. Requêtes avec select()

```python
# Utiliser select() pour les requêtes complexes
from sqlalchemy import select

async def find_users_by_email(db: AsyncSession, email: str):
    result = await db.execute(
        select(User).where(User.email == email)
    )
    return result.scalars().all()
```

### 4. Eager Loading pour Relations

```python
from sqlalchemy.orm import selectinload

async def get_user_with_posts(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(User)
        .options(selectinload(User.posts))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()
```

### 5. Relations Microservices

```python
# Pour les IDs d'autres services : pas de ForeignKey
class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ID d'un autre service - pas de foreign_key
    practitioner_id: Mapped[int] = mapped_column(Integer, index=True)
    # Relation dans le même service - avec foreign_key
    event_type_id: Mapped[int] = mapped_column(ForeignKey("event_types.id"))
```

### 6. Conversion Pydantic

```python
# Utiliser from_attributes pour la conversion ORM -> Pydantic
class UserResponse(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True


# Dans les endpoints
@router.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_session)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404)
    return UserResponse.model_validate(user)
```

## Conclusion

SQLAlchemy 2.0 avec Mapped[] offre :

- **Type safety** : Vérification statique complète avec mypy
- **Async natif** : Performance et scalabilité
- **Séparation claire** : ORM models vs API schemas
- **Puissance complète** : Toutes les fonctionnalités SQLAlchemy

Cette approche moderne permet un développement robuste avec validation de types et performances optimales.
