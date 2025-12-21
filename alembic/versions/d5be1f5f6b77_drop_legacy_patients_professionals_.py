"""Drop legacy patients and professionals tables after FHIR migration

Revision ID: d5be1f5f6b77
Revises: f0c3264fd0a5
Create Date: 2025-12-21 02:49:27.107615

IMPORTANT: Cette migration supprime les anciennes tables patients et professionals.
Assurez-vous que:
1. La migration vers HAPI FHIR est terminée (scripts/migrate_to_fhir.py)
2. Les tables GDPR metadata contiennent toutes les données
3. Vous avez une sauvegarde de la base de données

Pour revenir en arrière: alembic downgrade f0c3264fd0a5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5be1f5f6b77"
down_revision: str | None = "f0c3264fd0a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Supprime les anciennes tables patients et professionals.

    Ces tables sont remplacées par:
    - HAPI FHIR: données démographiques (Patient/Practitioner resources)
    - patient_gdpr_metadata: métadonnées RGPD locales
    - professional_gdpr_metadata: métadonnées RGPD locales
    """
    # Supprimer les anciennes tables
    op.drop_table("patients")
    op.drop_table("professionals")


def downgrade() -> None:
    """Recrée les anciennes tables patients et professionals.

    ATTENTION: Les données ne seront pas restaurées automatiquement.
    Vous devrez exporter les données depuis HAPI FHIR et les réimporter.
    """
    # Recréer la table professionals
    op.create_table(
        "professionals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "keycloak_user_id",
            sa.String(length=255),
            nullable=False,
            comment="UUID de l'utilisateur dans Keycloak",
        ),
        sa.Column(
            "professional_id",
            sa.String(length=50),
            nullable=True,
            comment="Numéro d'ordre professionnel (CNOM, etc.)",
        ),
        sa.Column(
            "first_name",
            sa.String(length=100),
            nullable=False,
            comment="Prénom du professionnel",
        ),
        sa.Column(
            "last_name",
            sa.String(length=100),
            nullable=False,
            comment="Nom de famille du professionnel",
        ),
        sa.Column(
            "title",
            sa.String(length=20),
            nullable=False,
            comment="Titre professionnel",
        ),
        sa.Column(
            "specialty",
            sa.String(length=100),
            nullable=False,
            comment="Spécialité médicale principale",
        ),
        sa.Column(
            "sub_specialty",
            sa.String(length=100),
            nullable=True,
            comment="Sous-spécialité médicale",
        ),
        sa.Column(
            "professional_type",
            sa.String(length=50),
            nullable=False,
            comment="Type de professionnel de santé",
        ),
        sa.Column(
            "email",
            sa.String(length=255),
            nullable=False,
            comment="Adresse email professionnelle",
        ),
        sa.Column(
            "phone",
            sa.String(length=20),
            nullable=False,
            comment="Téléphone professionnel au format E.164",
        ),
        sa.Column(
            "phone_secondary",
            sa.String(length=20),
            nullable=True,
            comment="Téléphone secondaire",
        ),
        sa.Column(
            "facility_name",
            sa.String(length=255),
            nullable=True,
            comment="Nom de l'établissement de santé",
        ),
        sa.Column(
            "facility_type",
            sa.String(length=50),
            nullable=True,
            comment="Type d'établissement",
        ),
        sa.Column(
            "facility_address",
            sa.String(length=500),
            nullable=True,
            comment="Adresse de l'établissement",
        ),
        sa.Column(
            "facility_city",
            sa.String(length=100),
            nullable=True,
            comment="Ville de l'établissement",
        ),
        sa.Column(
            "facility_region",
            sa.String(length=100),
            nullable=True,
            comment="Région de l'établissement",
        ),
        sa.Column(
            "qualifications",
            sa.Text(),
            nullable=True,
            comment="Diplômes et qualifications (JSON ou texte libre)",
        ),
        sa.Column(
            "years_of_experience",
            sa.Integer(),
            nullable=True,
            comment="Années d'expérience professionnelle",
        ),
        sa.Column(
            "languages_spoken",
            sa.String(length=100),
            nullable=False,
            server_default="fr",
            comment="Langues parlées (codes séparés par virgule: fr,en)",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Professionnel actif dans le système",
        ),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Informations professionnelles vérifiées",
        ),
        sa.Column(
            "is_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Disponible pour consultations",
        ),
        sa.Column(
            "under_investigation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Professionnel sous enquête médico-légale (bloque suppression)",
        ),
        sa.Column(
            "investigation_notes",
            sa.String(length=1000),
            nullable=True,
            comment="Notes sur l'enquête en cours",
        ),
        sa.Column(
            "correlation_hash",
            sa.String(length=64),
            nullable=True,
            comment="Hash SHA-256 de email+professional_id pour corrélation anonymisée",
        ),
        sa.Column(
            "soft_deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date de soft delete (début période de grâce 7 jours)",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date de suppression définitive (deprecated, use soft_deleted_at)",
        ),
        sa.Column(
            "deleted_by",
            sa.String(length=255),
            nullable=True,
            comment="Keycloak user ID de l'utilisateur qui a supprimé",
        ),
        sa.Column(
            "deletion_reason",
            sa.String(length=50),
            nullable=True,
            comment="Raison de la suppression",
        ),
        sa.Column(
            "anonymized_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date d'anonymisation définitive (après période de grâce)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Date de création du profil",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Date de dernière modification",
        ),
        sa.Column(
            "created_by",
            sa.String(length=255),
            nullable=True,
            comment="Keycloak user ID du créateur",
        ),
        sa.Column(
            "updated_by",
            sa.String(length=255),
            nullable=True,
            comment="Keycloak user ID du dernier modificateur",
        ),
        sa.Column("notes", sa.Text(), nullable=True, comment="Notes administratives"),
        sa.Column(
            "digital_signature",
            sa.Text(),
            nullable=True,
            comment="Signature numérique ou certificat pour ordonnances électroniques",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("keycloak_user_id"),
        sa.UniqueConstraint("professional_id"),
    )
    op.create_index("ix_professionals_id", "professionals", ["id"], unique=False)
    op.create_index(
        "ix_professionals_keycloak_user_id",
        "professionals",
        ["keycloak_user_id"],
        unique=False,
    )
    op.create_index("ix_professionals_email", "professionals", ["email"], unique=False)
    op.create_index(
        "ix_professionals_professional_id",
        "professionals",
        ["professional_id"],
        unique=False,
    )
    op.create_index(
        "ix_professionals_is_active", "professionals", ["is_active"], unique=False
    )
    op.create_index(
        "ix_professionals_under_investigation",
        "professionals",
        ["under_investigation"],
        unique=False,
    )
    op.create_index(
        "ix_professionals_correlation_hash",
        "professionals",
        ["correlation_hash"],
        unique=False,
    )
    op.create_index(
        "ix_professionals_soft_deleted_at",
        "professionals",
        ["soft_deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_professionals_deleted_at", "professionals", ["deleted_at"], unique=False
    )
    op.create_index(
        "ix_professionals_anonymized_at",
        "professionals",
        ["anonymized_at"],
        unique=False,
    )

    # Recréer la table patients
    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "keycloak_user_id",
            sa.String(length=255),
            nullable=False,
            comment="UUID de l'utilisateur dans Keycloak",
        ),
        sa.Column(
            "national_id",
            sa.String(length=50),
            nullable=True,
            comment="Numéro d'identification nationale (CNI, passeport, etc.)",
        ),
        sa.Column(
            "first_name",
            sa.String(length=100),
            nullable=False,
            comment="Prénom du patient",
        ),
        sa.Column(
            "last_name",
            sa.String(length=100),
            nullable=False,
            comment="Nom de famille du patient",
        ),
        sa.Column("date_of_birth", sa.Date(), nullable=False, comment="Date de naissance"),
        sa.Column("gender", sa.String(length=10), nullable=False, comment="Sexe biologique"),
        sa.Column(
            "email", sa.String(length=255), nullable=True, comment="Adresse email"
        ),
        sa.Column(
            "phone",
            sa.String(length=20),
            nullable=True,
            comment="Téléphone au format international E.164",
        ),
        sa.Column(
            "phone_secondary",
            sa.String(length=20),
            nullable=True,
            comment="Téléphone secondaire (famille, contact d'urgence)",
        ),
        sa.Column(
            "address_line1",
            sa.String(length=255),
            nullable=True,
            comment="Adresse principale",
        ),
        sa.Column(
            "address_line2",
            sa.String(length=255),
            nullable=True,
            comment="Complément d'adresse",
        ),
        sa.Column("city", sa.String(length=100), nullable=True, comment="Ville"),
        sa.Column(
            "region", sa.String(length=100), nullable=True, comment="Région administrative"
        ),
        sa.Column(
            "postal_code",
            sa.String(length=20),
            nullable=True,
            comment="Code postal (optionnel en Afrique)",
        ),
        sa.Column(
            "country",
            sa.String(length=100),
            nullable=False,
            server_default="Sénégal",
            comment="Pays de résidence",
        ),
        sa.Column(
            "latitude",
            sa.Float(),
            nullable=True,
            comment="Latitude GPS (format décimal)",
        ),
        sa.Column(
            "longitude",
            sa.Float(),
            nullable=True,
            comment="Longitude GPS (format décimal)",
        ),
        sa.Column(
            "emergency_contact_name",
            sa.String(length=200),
            nullable=True,
            comment="Nom du contact d'urgence",
        ),
        sa.Column(
            "emergency_contact_phone",
            sa.String(length=20),
            nullable=True,
            comment="Téléphone du contact d'urgence",
        ),
        sa.Column(
            "preferred_language",
            sa.String(length=5),
            nullable=False,
            server_default="fr",
            comment="Langue préférée (fr=Français, en=English)",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Patient actif dans le système",
        ),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Identité vérifiée par un professionnel",
        ),
        sa.Column(
            "under_investigation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Patient sous enquête (bloque suppression)",
        ),
        sa.Column(
            "investigation_notes",
            sa.String(length=1000),
            nullable=True,
            comment="Notes sur l'enquête en cours",
        ),
        sa.Column(
            "correlation_hash",
            sa.String(length=64),
            nullable=True,
            comment="Hash SHA-256 de email+national_id pour corrélation anonymisée",
        ),
        sa.Column(
            "soft_deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date de soft delete (début période de grâce 7 jours)",
        ),
        sa.Column(
            "anonymized_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date d'anonymisation définitive (après période de grâce)",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Date de suppression définitive (deprecated, use soft_deleted_at)",
        ),
        sa.Column(
            "deleted_by",
            sa.String(length=255),
            nullable=True,
            comment="Keycloak user ID de l'utilisateur qui a supprimé",
        ),
        sa.Column(
            "deletion_reason",
            sa.String(length=50),
            nullable=True,
            comment="Raison de la suppression",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Date de création du profil",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Date de dernière modification",
        ),
        sa.Column(
            "created_by",
            sa.String(length=255),
            nullable=True,
            comment="Keycloak user ID du créateur",
        ),
        sa.Column(
            "updated_by",
            sa.String(length=255),
            nullable=True,
            comment="Keycloak user ID du dernier modificateur",
        ),
        sa.Column(
            "notes", sa.Text(), nullable=True, comment="Notes administratives (non médicales)"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("keycloak_user_id"),
        sa.UniqueConstraint("national_id"),
    )
    op.create_index("ix_patients_id", "patients", ["id"], unique=False)
    op.create_index(
        "ix_patients_keycloak_user_id", "patients", ["keycloak_user_id"], unique=False
    )
    op.create_index("ix_patients_national_id", "patients", ["national_id"], unique=False)
    op.create_index("ix_patients_email", "patients", ["email"], unique=False)
    op.create_index("ix_patients_is_active", "patients", ["is_active"], unique=False)
    op.create_index(
        "ix_patients_under_investigation",
        "patients",
        ["under_investigation"],
        unique=False,
    )
    op.create_index(
        "ix_patients_correlation_hash", "patients", ["correlation_hash"], unique=False
    )
    op.create_index(
        "ix_patients_soft_deleted_at", "patients", ["soft_deleted_at"], unique=False
    )
    op.create_index(
        "ix_patients_anonymized_at", "patients", ["anonymized_at"], unique=False
    )
    op.create_index("ix_patients_deleted_at", "patients", ["deleted_at"], unique=False)
