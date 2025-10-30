"""
Configuration et initialisation de la base de données pour core-africare-identity.

Base de données: PostgreSQL avec SQLModel et AsyncSession
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class pour tous les modèles SQLAlchemy."""

    pass


# Engine SQLAlchemy 2.0
engine = create_async_engine(str(settings.SQLALCHEMY_DATABASE_URI), echo=False)  # settings.DEBUG)

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


# Export pour compatibilité
get_db = get_session
