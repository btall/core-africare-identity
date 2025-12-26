# Modèles GDPR Locaux

Ce document décrit les modèles SQLAlchemy pour stocker les métadonnées GDPR localement dans PostgreSQL.

## Architecture

```
HAPI FHIR                       PostgreSQL
┌─────────────────┐             ┌─────────────────────────┐
│ Patient         │             │ PatientGdprMetadata     │
│  - name         │             │  - id (PK local)        │
│  - telecom      │ ←────────→  │  - fhir_resource_id     │
│  - birthDate    │             │  - keycloak_user_id     │
│  - identifier[] │             │  - soft_deleted_at      │
└─────────────────┘             │  - anonymized_at        │
                                │  - correlation_hash     │
                                └─────────────────────────┘
```

## Modèle PatientGdprMetadata

**Fichier**: `app/models/gdpr_metadata.py`

```python
"""Modèles SQLAlchemy pour métadonnées GDPR locales."""

from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, String, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PatientGdprMetadata(Base):
    """
    Métadonnées GDPR pour Patient (stockées localement).

    Le Patient FHIR est stocké dans HAPI FHIR, ce modèle ne contient
    que les métadonnées nécessaires pour la conformité GDPR.
    """

    __tablename__ = "patient_gdpr_metadata"

    # Identifiants
    id: Mapped[int] = mapped_column(primary_key=True)
    fhir_resource_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        comment="ID de la ressource Patient dans HAPI FHIR",
    )
    keycloak_user_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
        comment="UUID Keycloak pour lookup rapide",
    )

    # Vérification
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Identité vérifiée",
    )

    # GDPR - Suppression
    under_investigation: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
        comment="Bloque la suppression si True",
    )
    investigation_notes: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    correlation_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Hash pour détection retour après anonymisation",
    )
    soft_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Début période de grâce (7 jours)",
    )
    anonymized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Date d'anonymisation définitive",
    )
    deletion_reason: Mapped[Literal[
        "user_request",
        "admin_termination",
        "gdpr_compliance",
        "prolonged_inactivity",
    ] | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProfessionalGdprMetadata(Base):
    """
    Métadonnées GDPR pour Practitioner (stockées localement).

    Le Practitioner FHIR est stocké dans HAPI FHIR.
    """

    __tablename__ = "professional_gdpr_metadata"

    # Identifiants
    id: Mapped[int] = mapped_column(primary_key=True)
    fhir_resource_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        comment="ID de la ressource Practitioner dans HAPI FHIR",
    )
    keycloak_user_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
        comment="UUID Keycloak",
    )

    # Vérification professionnelle
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_available: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        comment="Disponible pour rendez-vous",
    )
    has_digital_signature: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Signature numérique configurée",
    )

    # GDPR - Suppression
    under_investigation: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
    )
    investigation_notes: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    correlation_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    soft_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    anonymized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    deletion_reason: Mapped[Literal[
        "user_request",
        "admin_termination",
        "professional_revocation",
        "gdpr_compliance",
        "prolonged_inactivity",
    ] | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
```

## Migration Alembic

```bash
# Créer la migration
make migrate MESSAGE="Add GDPR metadata tables for FHIR hybrid architecture"

# Appliquer
make migrate-up
```

**Contenu migration attendu**:

```python
def upgrade():
    op.create_table(
        'patient_gdpr_metadata',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('fhir_resource_id', sa.String(64), unique=True, index=True),
        sa.Column('keycloak_user_id', sa.String(36), unique=True, index=True),
        sa.Column('is_verified', sa.Boolean(), default=False),
        sa.Column('under_investigation', sa.Boolean(), default=False, index=True),
        sa.Column('investigation_notes', sa.String(1000), nullable=True),
        sa.Column('correlation_hash', sa.String(64), nullable=True, index=True),
        sa.Column('soft_deleted_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('anonymized_at', sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column('deletion_reason', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        'professional_gdpr_metadata',
        # ... similaire
    )


def downgrade():
    op.drop_table('professional_gdpr_metadata')
    op.drop_table('patient_gdpr_metadata')
```

## Requêtes Courantes

### Trouver par Keycloak ID

```python
async def get_by_keycloak_id(
    db: AsyncSession,
    keycloak_user_id: str,
) -> PatientGdprMetadata | None:
    result = await db.execute(
        select(PatientGdprMetadata).where(
            PatientGdprMetadata.keycloak_user_id == keycloak_user_id
        )
    )
    return result.scalar_one_or_none()
```

### Trouver par FHIR Resource ID

```python
async def get_by_fhir_id(
    db: AsyncSession,
    fhir_resource_id: str,
) -> PatientGdprMetadata | None:
    result = await db.execute(
        select(PatientGdprMetadata).where(
            PatientGdprMetadata.fhir_resource_id == fhir_resource_id
        )
    )
    return result.scalar_one_or_none()
```

### Trouver les suppressions expirées

```python
async def get_expired_soft_deletions(
    db: AsyncSession,
    grace_period_days: int = 7,
) -> list[PatientGdprMetadata]:
    threshold = datetime.now(UTC) - timedelta(days=grace_period_days)
    result = await db.execute(
        select(PatientGdprMetadata).where(
            PatientGdprMetadata.soft_deleted_at.isnot(None),
            PatientGdprMetadata.soft_deleted_at <= threshold,
            PatientGdprMetadata.anonymized_at.is_(None),
        )
    )
    return result.scalars().all()
```
