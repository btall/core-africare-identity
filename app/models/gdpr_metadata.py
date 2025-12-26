"""Modeles GDPR locaux pour architecture hybride FHIR.

Ces tables maintiennent les metadonnees non-FHIR localement:
- IDs numeriques pour retrocompatibilite API
- Reference vers ressources FHIR (fhir_resource_id)
- Champs GDPR (soft delete, anonymisation, enquete)
- Statuts specifiques non-standard FHIR
"""

from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Types de raison de suppression
PatientDeletionReason = Literal[
    "user_request",
    "admin_request",
    "gdpr_compliance",
    "prolonged_inactivity",
    "deceased",
    "other",
]

ProfessionalDeletionReason = Literal[
    "user_request",
    "admin_termination",
    "professional_revocation",
    "gdpr_compliance",
    "prolonged_inactivity",
    "other",
]


class PatientGdprMetadata(Base):
    """Metadonnees GDPR locales pour Patient.

    Cette table maintient:
    - ID numerique (retro-compatibilite API)
    - Reference vers ressource FHIR Patient
    - Champs GDPR non-standard FHIR
    - Statuts de verification et notes

    La cle primaire (id) utilise la meme sequence que l'ancienne
    table patients pour garantir la continuite des IDs.
    """

    __tablename__ = "patient_gdpr_metadata"

    # Identifiants
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="ID numerique local (retro-compatibilite API)",
    )
    fhir_resource_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="ID de la ressource FHIR Patient (UUID serveur HAPI)",
    )
    keycloak_user_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="UUID Keycloak pour lookups rapides",
    )

    # Champs non-FHIR
    is_verified: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        comment="Informations patient verifiees",
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Notes administratives",
    )

    # RGPD - Enquete medico-legale
    under_investigation: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        index=True,
        comment="Patient sous enquete medico-legale (bloque suppression)",
    )
    investigation_notes: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="Notes sur l'enquete en cours",
    )

    # RGPD - Correlation anonymisee
    correlation_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Hash SHA-256 de email+phone pour correlation post-anonymisation",
    )

    # RGPD - Soft delete et anonymisation
    soft_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Date de soft delete (debut periode de grace 7 jours)",
    )
    anonymized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Date d'anonymisation definitive (apres periode de grace)",
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Keycloak user ID de l'utilisateur qui a supprime",
    )
    deletion_reason: Mapped[PatientDeletionReason | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Raison de la suppression",
    )

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Date de creation du profil",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Date de derniere modification",
    )
    created_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Keycloak user ID du createur",
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Keycloak user ID du dernier modificateur",
    )

    def __repr__(self) -> str:
        """Representation string des metadonnees patient."""
        return (
            f"<PatientGdprMetadata(id={self.id}, "
            f"fhir_id='{self.fhir_resource_id}', "
            f"keycloak='{self.keycloak_user_id[:8]}...')>"
        )

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour le mapper FHIR."""
        return {
            "is_verified": self.is_verified,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
        }


class ProfessionalGdprMetadata(Base):
    """Metadonnees GDPR locales pour Professional.

    Cette table maintient:
    - ID numerique (retro-compatibilite API)
    - Reference vers ressource FHIR Practitioner
    - Champs GDPR non-standard FHIR
    - Statuts specifiques aux professionnels (disponibilite, signature)
    """

    __tablename__ = "professional_gdpr_metadata"

    # Identifiants
    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
        comment="ID numerique local (retro-compatibilite API)",
    )
    fhir_resource_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="ID de la ressource FHIR Practitioner (UUID serveur HAPI)",
    )
    keycloak_user_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="UUID Keycloak pour lookups rapides",
    )

    # Champs non-FHIR specifiques aux professionnels
    is_verified: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        comment="Informations professionnelles verifiees",
    )
    is_available: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        comment="Disponible pour consultations",
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Notes administratives",
    )

    # Signature numerique (pour prescriptions electroniques)
    digital_signature: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Signature numerique ou certificat pour ordonnances electroniques",
    )

    # RGPD - Enquete medico-legale
    under_investigation: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        index=True,
        comment="Professionnel sous enquete medico-legale (bloque suppression)",
    )
    investigation_notes: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
        comment="Notes sur l'enquete en cours",
    )

    # RGPD - Correlation anonymisee
    correlation_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Hash SHA-256 de email+professional_id pour correlation post-anonymisation",
    )

    # RGPD - Soft delete et anonymisation
    soft_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Date de soft delete (debut periode de grace 7 jours)",
    )
    anonymized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Date d'anonymisation definitive (apres periode de grace)",
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Keycloak user ID de l'utilisateur qui a supprime",
    )
    deletion_reason: Mapped[ProfessionalDeletionReason | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Raison de la suppression",
    )

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Date de creation du profil",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Date de derniere modification",
    )
    created_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Keycloak user ID du createur",
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Keycloak user ID du dernier modificateur",
    )

    def __repr__(self) -> str:
        """Representation string des metadonnees professionnel."""
        return (
            f"<ProfessionalGdprMetadata(id={self.id}, "
            f"fhir_id='{self.fhir_resource_id}', "
            f"keycloak='{self.keycloak_user_id[:8]}...')>"
        )

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour le mapper FHIR."""
        return {
            "is_verified": self.is_verified,
            "is_available": self.is_available,
            "notes": self.notes,
            "digital_signature": self.digital_signature,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
        }
