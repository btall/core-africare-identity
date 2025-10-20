"""Add soft delete fields to patients and professionals

Revision ID: 1374f3c565ad
Revises: 2463648ab224
Create Date: 2025-10-20 22:19:02.654554

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1374f3c565ad"
down_revision: str | None = "2463648ab224"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ajouter champs soft delete à la table patients
    op.add_column(
        "patients",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date de suppression (soft delete)",
        ),
    )
    op.add_column(
        "patients",
        sa.Column(
            "deleted_by",
            sa.String(length=255),
            nullable=True,
            comment="Keycloak user ID de l'utilisateur qui a supprimé",
        ),
    )
    op.add_column(
        "patients",
        sa.Column(
            "deletion_reason",
            sa.String(length=50),
            nullable=True,
            comment="Raison de la suppression",
        ),
    )
    op.create_index(op.f("ix_patients_deleted_at"), "patients", ["deleted_at"], unique=False)

    # Ajouter champs soft delete à la table professionals
    op.add_column(
        "professionals",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date de suppression (soft delete)",
        ),
    )
    op.add_column(
        "professionals",
        sa.Column(
            "deleted_by",
            sa.String(length=255),
            nullable=True,
            comment="Keycloak user ID de l'utilisateur qui a supprimé",
        ),
    )
    op.add_column(
        "professionals",
        sa.Column(
            "deletion_reason",
            sa.String(length=50),
            nullable=True,
            comment="Raison de la suppression",
        ),
    )
    op.create_index(
        op.f("ix_professionals_deleted_at"), "professionals", ["deleted_at"], unique=False
    )


def downgrade() -> None:
    # Rollback pour professionals
    op.drop_index(op.f("ix_professionals_deleted_at"), table_name="professionals")
    op.drop_column("professionals", "deletion_reason")
    op.drop_column("professionals", "deleted_by")
    op.drop_column("professionals", "deleted_at")

    # Rollback pour patients
    op.drop_index(op.f("ix_patients_deleted_at"), table_name="patients")
    op.drop_column("patients", "deletion_reason")
    op.drop_column("patients", "deleted_by")
    op.drop_column("patients", "deleted_at")
