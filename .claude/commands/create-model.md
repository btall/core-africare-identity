---
name: create-model
description: Génère un modèle SQLAlchemy 2.0 avec métadonnées GDPR, timestamps timezone et contraintes PostgreSQL 18
---

# Créer un Modèle SQLAlchemy GDPR

Cette commande génère un modèle SQLAlchemy 2.0 avec les métadonnées GDPR requises pour le projet AfriCare. Le modèle inclut automatiquement les champs de conformité RGPD, les timestamps avec timezone, et les contraintes temporelles PostgreSQL 18.

## Utilisation

```
/create-model <nom_entite> [description]
```

**Exemples:**
- `/create-model patient` - Créer le modèle Patient
- `/create-model professional` - Créer le modèle Professional
- `/create-model appointment` - Créer le modèle Appointment avec contraintes temporelles

## Template Modèle Standard

### Structure de fichier

**Fichier**: `app/models/{entity}.py`

```python
"""Modèle SQLAlchemy pour {Entity} avec métadonnées GDPR."""

from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import DateTime, String, Boolean, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class {Entity}(Base):
    """
    Modèle {Entity} avec conformité GDPR.

    Champs GDPR:
    - soft_deleted_at: Date de suppression douce (période de grâce 7j)
    - anonymized_at: Date d'anonymisation définitive
    - correlation_hash: Hash SHA-256 pour détection de retour

    Attributs:
        id: Identifiant unique auto-incrémenté
        keycloak_user_id: ID utilisateur Keycloak (lookup rapide)
        is_active: Indique si l'entité est active
        created_at: Date de création (timezone-aware)
        updated_at: Date de dernière modification (timezone-aware)
    """

    __tablename__ = "{entity}s"

    # Identifiants
    id: Mapped[int] = mapped_column(primary_key=True)
    keycloak_user_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
        comment="UUID Keycloak pour lookup rapide",
    )

    # Données de base
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # État
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        index=True,
        comment="Entité active (False = soft deleted)",
    )

    # Métadonnées GDPR
    under_investigation: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
        comment="Sous enquête médico-légale (bloque suppression)",
    )
    investigation_notes: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
        comment="Notes d'enquête (admin only)",
    )
    correlation_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Hash SHA-256 de email+id pour corrélation anonymisée",
    )
    soft_deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Date de soft delete (début période de grâce 7 jours)",
    )
    anonymized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Date d'anonymisation définitive (après période de grâce)",
    )
    deletion_reason: Mapped[Optional[Literal[
        "user_request",
        "admin_termination",
        "professional_revocation",
        "gdpr_compliance",
        "prolonged_inactivity",
    ]]] = mapped_column(
        String(50),
        nullable=True,
        comment="Raison de la suppression",
    )

    # Timestamps (toujours timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="Date de création UTC",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="Date de dernière modification UTC",
    )

    # Index composites pour requêtes fréquentes
    __table_args__ = (
        Index("ix_{entity}s_active_created", "is_active", "created_at"),
        Index("ix_{entity}s_soft_deleted", "soft_deleted_at", "anonymized_at"),
    )

    def __repr__(self) -> str:
        return f"<{Entity}(id={self.id}, email={self.email}, is_active={self.is_active})>"
```

## Template Modèle avec Contraintes Temporelles (PostgreSQL 18)

Pour les entités avec périodes de validité (rendez-vous, tarifs, etc.):

```python
"""Modèle avec contraintes temporelles PostgreSQL 18 WITHOUT OVERLAPS."""

from datetime import datetime
from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import TSTZRANGE
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class {Entity}(Base):
    """
    Modèle {Entity} avec contraintes temporelles.

    Utilise PostgreSQL 18 WITHOUT OVERLAPS pour garantir
    l'absence de chevauchement des périodes.
    """

    __tablename__ = "{entity}s"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_period: Mapped[TSTZRANGE] = mapped_column(TSTZRANGE, nullable=False)
    description: Mapped[str] = mapped_column(String(500))

    # Note: PRIMARY KEY avec WITHOUT OVERLAPS doit être défini via Alembic
    # Voir migration template ci-dessous
```

### Migration Alembic pour WITHOUT OVERLAPS

```python
# alembic/versions/xxx_add_{entity}_temporal.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    # Créer extension btree_gist si nécessaire
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # Créer table avec colonnes de base
    op.create_table(
        '{entity}s',
        sa.Column('id', sa.Integer(), autoincrement=True),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('valid_period', postgresql.TSTZRANGE(), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
    )

    # Ajouter contrainte UNIQUE avec WITHOUT OVERLAPS (PostgreSQL 18+)
    op.execute("""
        ALTER TABLE {entity}s
        ADD CONSTRAINT uq_{entity}s_resource_period
        UNIQUE (resource_id, valid_period WITHOUT OVERLAPS)
    """)

def downgrade():
    op.drop_table('{entity}s')
```

## Intégration

**Ajouter dans** `app/models/__init__.py`:

```python
from app.models.{entity} import {Entity}

__all__ = [
    # ... autres modèles
    "{Entity}",
]
```

## Checklist

- [ ] Créer le fichier modèle `app/models/{entity}.py`
- [ ] Ajouter l'import dans `app/models/__init__.py`
- [ ] Créer la migration: `make migrate MESSAGE="Add {entity} table"`
- [ ] Appliquer la migration: `make migrate-up`
- [ ] Créer les schémas Pydantic: `/create-schema {entity}`
- [ ] Exécuter `make lint` et `make test`

## Conventions AfriCare

### Types SQLAlchemy 2.0

| Type Python | Type SQLAlchemy | Usage |
|-------------|-----------------|-------|
| `Mapped[int]` | `mapped_column(primary_key=True)` | ID auto-incrémenté |
| `Mapped[str]` | `mapped_column(String(n))` | Texte limité |
| `Mapped[Optional[str]]` | `mapped_column(String(n), nullable=True)` | Texte optionnel |
| `Mapped[bool]` | `mapped_column(Boolean, default=True)` | Booléen avec défaut |
| `Mapped[datetime]` | `mapped_column(DateTime(timezone=True))` | Date avec timezone |
| `Mapped[Literal[...]]` | `mapped_column(String(n))` | Enum-like |

### Nommage Tables

- **Table**: snake_case pluriel (`patients`, `professionals`, `appointments`)
- **Colonnes**: snake_case (`created_at`, `keycloak_user_id`)
- **Index**: `ix_{table}_{column}` ou `ix_{table}_{col1}_{col2}`
- **Contraintes**: `fk_{table}_{ref_table}`, `uq_{table}_{column}`

### Champs GDPR Obligatoires

Pour toute entité contenant des données personnelles:

1. `is_active` - Flag de soft delete
2. `soft_deleted_at` - Début période de grâce
3. `anonymized_at` - Anonymisation définitive
4. `correlation_hash` - Détection retour (optionnel)
5. `under_investigation` - Blocage suppression légale

### Timestamps

**TOUJOURS** utiliser `DateTime(timezone=True)`:

```python
# Correct
created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now()
)

# Incorrect (timezone naive)
created_at: Mapped[datetime] = mapped_column(DateTime())
```

## Ressources

- **Patterns SQLAlchemy**: Voir `CLAUDE.md` section "Database Operations"
- **Contraintes temporelles**: Voir section "Temporal Constraints PostgreSQL 18+"
- **Migrations**: Voir `alembic/` pour exemples existants
