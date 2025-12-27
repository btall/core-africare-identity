"""Add GDPR metadata tables for FHIR hybrid architecture

Revision ID: f0c3264fd0a5
Revises: 334ba84e6c89
Create Date: 2025-12-18 02:16:47.469992

This migration creates the GDPR metadata tables for the hybrid FHIR architecture:
- patient_gdpr_metadata: Local metadata for Patient (FHIR stores demographics)
- professional_gdpr_metadata: Local metadata for Professional (FHIR stores demographics)

These tables maintain:
- Numeric IDs for API retrocompatibility
- Reference to FHIR resources (fhir_resource_id)
- GDPR fields not in FHIR standard (soft_deleted_at, anonymized_at, etc.)
- Business-specific fields (is_verified, is_available, digital_signature)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0c3264fd0a5"
down_revision: str | None = "334ba84e6c89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create patient_gdpr_metadata table
    op.create_table(
        "patient_gdpr_metadata",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
            comment="ID numerique local (retro-compatibilite API)",
        ),
        sa.Column(
            "fhir_resource_id",
            sa.String(64),
            nullable=False,
            comment="ID de la ressource FHIR Patient (UUID serveur HAPI)",
        ),
        sa.Column(
            "keycloak_user_id",
            sa.String(255),
            nullable=False,
            comment="UUID Keycloak pour lookups rapides",
        ),
        # Non-FHIR fields
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Informations patient verifiees",
        ),
        sa.Column("notes", sa.Text(), nullable=True, comment="Notes administratives"),
        # GDPR - Investigation
        sa.Column(
            "under_investigation",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Patient sous enquete medico-legale (bloque suppression)",
        ),
        sa.Column(
            "investigation_notes",
            sa.String(1000),
            nullable=True,
            comment="Notes sur l'enquete en cours",
        ),
        # GDPR - Correlation
        sa.Column(
            "correlation_hash",
            sa.String(64),
            nullable=True,
            comment="Hash SHA-256 de email+phone pour correlation post-anonymisation",
        ),
        # GDPR - Soft delete and anonymization
        sa.Column(
            "soft_deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date de soft delete (debut periode de grace 7 jours)",
        ),
        sa.Column(
            "anonymized_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date d'anonymisation definitive (apres periode de grace)",
        ),
        sa.Column(
            "deleted_by",
            sa.String(255),
            nullable=True,
            comment="Keycloak user ID de l'utilisateur qui a supprime",
        ),
        sa.Column(
            "deletion_reason", sa.String(50), nullable=True, comment="Raison de la suppression"
        ),
        # Audit
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Date de creation du profil",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            comment="Date de derniere modification",
        ),
        sa.Column(
            "created_by", sa.String(255), nullable=True, comment="Keycloak user ID du createur"
        ),
        sa.Column(
            "updated_by",
            sa.String(255),
            nullable=True,
            comment="Keycloak user ID du dernier modificateur",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for patient_gdpr_metadata
    op.create_index("ix_patient_gdpr_metadata_id", "patient_gdpr_metadata", ["id"])
    op.create_index(
        "ix_patient_gdpr_metadata_fhir_resource_id",
        "patient_gdpr_metadata",
        ["fhir_resource_id"],
        unique=True,
    )
    op.create_index(
        "ix_patient_gdpr_metadata_keycloak_user_id",
        "patient_gdpr_metadata",
        ["keycloak_user_id"],
        unique=True,
    )
    op.create_index(
        "ix_patient_gdpr_metadata_under_investigation",
        "patient_gdpr_metadata",
        ["under_investigation"],
    )
    op.create_index(
        "ix_patient_gdpr_metadata_correlation_hash", "patient_gdpr_metadata", ["correlation_hash"]
    )
    op.create_index(
        "ix_patient_gdpr_metadata_soft_deleted_at", "patient_gdpr_metadata", ["soft_deleted_at"]
    )
    op.create_index(
        "ix_patient_gdpr_metadata_anonymized_at", "patient_gdpr_metadata", ["anonymized_at"]
    )

    # Create professional_gdpr_metadata table
    op.create_table(
        "professional_gdpr_metadata",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
            comment="ID numerique local (retro-compatibilite API)",
        ),
        sa.Column(
            "fhir_resource_id",
            sa.String(64),
            nullable=False,
            comment="ID de la ressource FHIR Practitioner (UUID serveur HAPI)",
        ),
        sa.Column(
            "keycloak_user_id",
            sa.String(255),
            nullable=False,
            comment="UUID Keycloak pour lookups rapides",
        ),
        # Non-FHIR fields specific to professionals
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Informations professionnelles verifiees",
        ),
        sa.Column(
            "is_available",
            sa.Boolean(),
            nullable=False,
            server_default="true",
            comment="Disponible pour consultations",
        ),
        sa.Column("notes", sa.Text(), nullable=True, comment="Notes administratives"),
        sa.Column(
            "digital_signature",
            sa.Text(),
            nullable=True,
            comment="Signature numerique ou certificat pour ordonnances electroniques",
        ),
        # GDPR - Investigation
        sa.Column(
            "under_investigation",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Professionnel sous enquete medico-legale (bloque suppression)",
        ),
        sa.Column(
            "investigation_notes",
            sa.String(1000),
            nullable=True,
            comment="Notes sur l'enquete en cours",
        ),
        # GDPR - Correlation
        sa.Column(
            "correlation_hash",
            sa.String(64),
            nullable=True,
            comment="Hash SHA-256 de email+professional_id pour correlation post-anonymisation",
        ),
        # GDPR - Soft delete and anonymization
        sa.Column(
            "soft_deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date de soft delete (debut periode de grace 7 jours)",
        ),
        sa.Column(
            "anonymized_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date d'anonymisation definitive (apres periode de grace)",
        ),
        sa.Column(
            "deleted_by",
            sa.String(255),
            nullable=True,
            comment="Keycloak user ID de l'utilisateur qui a supprime",
        ),
        sa.Column(
            "deletion_reason", sa.String(50), nullable=True, comment="Raison de la suppression"
        ),
        # Audit
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Date de creation du profil",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            comment="Date de derniere modification",
        ),
        sa.Column(
            "created_by", sa.String(255), nullable=True, comment="Keycloak user ID du createur"
        ),
        sa.Column(
            "updated_by",
            sa.String(255),
            nullable=True,
            comment="Keycloak user ID du dernier modificateur",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for professional_gdpr_metadata
    op.create_index("ix_professional_gdpr_metadata_id", "professional_gdpr_metadata", ["id"])
    op.create_index(
        "ix_professional_gdpr_metadata_fhir_resource_id",
        "professional_gdpr_metadata",
        ["fhir_resource_id"],
        unique=True,
    )
    op.create_index(
        "ix_professional_gdpr_metadata_keycloak_user_id",
        "professional_gdpr_metadata",
        ["keycloak_user_id"],
        unique=True,
    )
    op.create_index(
        "ix_professional_gdpr_metadata_under_investigation",
        "professional_gdpr_metadata",
        ["under_investigation"],
    )
    op.create_index(
        "ix_professional_gdpr_metadata_correlation_hash",
        "professional_gdpr_metadata",
        ["correlation_hash"],
    )
    op.create_index(
        "ix_professional_gdpr_metadata_soft_deleted_at",
        "professional_gdpr_metadata",
        ["soft_deleted_at"],
    )
    op.create_index(
        "ix_professional_gdpr_metadata_anonymized_at",
        "professional_gdpr_metadata",
        ["anonymized_at"],
    )


def downgrade() -> None:
    # Drop professional_gdpr_metadata indexes and table
    op.drop_index("ix_professional_gdpr_metadata_anonymized_at", "professional_gdpr_metadata")
    op.drop_index("ix_professional_gdpr_metadata_soft_deleted_at", "professional_gdpr_metadata")
    op.drop_index("ix_professional_gdpr_metadata_correlation_hash", "professional_gdpr_metadata")
    op.drop_index("ix_professional_gdpr_metadata_under_investigation", "professional_gdpr_metadata")
    op.drop_index("ix_professional_gdpr_metadata_keycloak_user_id", "professional_gdpr_metadata")
    op.drop_index("ix_professional_gdpr_metadata_fhir_resource_id", "professional_gdpr_metadata")
    op.drop_index("ix_professional_gdpr_metadata_id", "professional_gdpr_metadata")
    op.drop_table("professional_gdpr_metadata")

    # Drop patient_gdpr_metadata indexes and table
    op.drop_index("ix_patient_gdpr_metadata_anonymized_at", "patient_gdpr_metadata")
    op.drop_index("ix_patient_gdpr_metadata_soft_deleted_at", "patient_gdpr_metadata")
    op.drop_index("ix_patient_gdpr_metadata_correlation_hash", "patient_gdpr_metadata")
    op.drop_index("ix_patient_gdpr_metadata_under_investigation", "patient_gdpr_metadata")
    op.drop_index("ix_patient_gdpr_metadata_keycloak_user_id", "patient_gdpr_metadata")
    op.drop_index("ix_patient_gdpr_metadata_fhir_resource_id", "patient_gdpr_metadata")
    op.drop_index("ix_patient_gdpr_metadata_id", "patient_gdpr_metadata")
    op.drop_table("patient_gdpr_metadata")
