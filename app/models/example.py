"""
Modèles d'exemple pour core-africare-identity.

Utilise SQLModel pour PostgreSQL (modèles unifiés table + API).
"""

from typing import Optional
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel, Field
from app.core.database import Base


class Example(Base):
    """Modèle de table SQLAlchemy pour PostgreSQL."""
    __tablename__ = "examples"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(1000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None, onupdate=func.now())


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
