"""Modèle de données Professional pour le service Identity.

Ce module définit le modèle SQLAlchemy pour les professionnels de santé
du système AfriCare.
"""

from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Professional(Base):
    """
    Modèle Professional pour les praticiens de santé.

    Champs clés :
    - Intégration Keycloak via keycloak_user_id
    - Numéro d'ordre professionnel (CNOM au Sénégal, etc.)
    - Spécialité médicale
    - Établissement de rattachement
    - Informations de contact professionnel
    """

    __tablename__ = "professionals"

    # Identifiants
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    keycloak_user_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="UUID de l'utilisateur dans Keycloak"
    )
    professional_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        unique=True,
        nullable=True,
        index=True,
        comment="Numéro d'ordre professionnel (CNOM, etc.)"
    )

    # Informations personnelles
    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Prénom du professionnel"
    )
    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Nom de famille du professionnel"
    )
    title: Mapped[Literal["Dr", "Pr", "Inf", "Sage-femme", "Pharmacien", "Autre"]] = (
        mapped_column(
            String(20),
            nullable=False,
            default="Dr",
            comment="Titre professionnel"
        )
    )

    # Informations professionnelles
    specialty: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Spécialité médicale principale"
    )
    sub_specialty: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Sous-spécialité médicale"
    )
    professional_type: Mapped[
        Literal["physician", "nurse", "midwife", "pharmacist", "technician", "other"]
    ] = mapped_column(
        String(50),
        nullable=False,
        comment="Type de professionnel de santé"
    )

    # Informations de contact professionnel
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Adresse email professionnelle"
    )
    phone: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Téléphone professionnel au format E.164"
    )
    phone_secondary: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Téléphone secondaire"
    )

    # Établissement de rattachement
    facility_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Nom de l'établissement de santé"
    )
    facility_type: Mapped[
        Optional[Literal["hospital", "clinic", "health_post", "private_practice", "other"]]
    ] = mapped_column(
        String(50),
        nullable=True,
        comment="Type d'établissement"
    )
    facility_address: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Adresse de l'établissement"
    )
    facility_city: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Ville de l'établissement"
    )
    facility_region: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Région de l'établissement"
    )

    # Qualifications
    qualifications: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Diplômes et qualifications (JSON ou texte libre)"
    )
    years_of_experience: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        comment="Années d'expérience professionnelle"
    )

    # Langue(s) parlée(s)
    languages_spoken: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="fr",
        comment="Langues parlées (codes séparés par virgule: fr,wo,en)"
    )

    # Disponibilité et statut
    is_active: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        index=True,
        comment="Professionnel actif dans le système"
    )
    is_verified: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        comment="Informations professionnelles vérifiées"
    )
    is_available: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        comment="Disponible pour consultations"
    )

    # Métadonnées
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Date de création du profil"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Date de dernière modification"
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Keycloak user ID du créateur"
    )
    updated_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Keycloak user ID du dernier modificateur"
    )

    # Notes administratives
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Notes administratives"
    )

    # Signature numérique (optionnel pour prescriptions)
    digital_signature: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Signature numérique ou certificat pour ordonnances électroniques"
    )

    def __repr__(self) -> str:
        """Représentation string du professionnel."""
        return (
            f"<Professional(id={self.id}, "
            f"name='{self.title} {self.first_name} {self.last_name}', "
            f"specialty='{self.specialty}')>"
        )
