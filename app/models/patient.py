"""Modèle de données Patient pour le service Identity.

Ce module définit le modèle SQLAlchemy pour les patients du système AfriCare,
optimisé pour le contexte africain avec support GPS et identifiants locaux.
"""

from datetime import date, datetime
from typing import Literal

from sqlalchemy import Date, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Patient(Base):
    """
    Modèle Patient avec support des standards de santé et contexte africain.

    Champs clés :
    - Intégration Keycloak via keycloak_user_id
    - Support GPS pour localisation en zones rurales
    - Identifiants nationaux (carte d'identité, etc.)
    - Multilingue (prénom/nom peuvent inclure caractères spéciaux)
    - Contact d'urgence pour situations critiques

    Note: Les données médicales (groupe sanguin, allergies, historique médical)
    sont gérées par le service core-africare-ehr.
    """

    __tablename__ = "patients"

    # Identifiants
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    keycloak_user_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="UUID de l'utilisateur dans Keycloak",
    )
    national_id: Mapped[str | None] = mapped_column(
        String(50),
        unique=True,
        nullable=True,
        index=True,
        comment="Numéro d'identification nationale (CNI, passeport, etc.)",
    )

    # Informations démographiques
    first_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Prénom du patient"
    )
    last_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Nom de famille du patient"
    )
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False, comment="Date de naissance")
    gender: Mapped[Literal["male", "female", "other", "unknown"]] = mapped_column(
        String(20), nullable=False, comment="Sexe biologique"
    )

    # Informations de contact
    email: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True, comment="Adresse email"
    )
    phone: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="Téléphone au format international E.164"
    )
    phone_secondary: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="Téléphone secondaire (famille, contact d'urgence)"
    )

    # Adresse physique
    address_line1: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Adresse principale"
    )
    address_line2: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Complément d'adresse"
    )
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="Ville")
    region: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Région administrative"
    )
    postal_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="Code postal (optionnel en Afrique)"
    )
    country: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Sénégal", comment="Pays de résidence"
    )

    # Localisation GPS (important pour zones rurales)
    latitude: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Latitude GPS (format décimal)"
    )
    longitude: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Longitude GPS (format décimal)"
    )

    # Contact d'urgence
    emergency_contact_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="Nom du contact d'urgence"
    )
    emergency_contact_phone: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="Téléphone du contact d'urgence"
    )

    # Langue préférée pour communication
    preferred_language: Mapped[Literal["fr", "en"]] = mapped_column(
        String(5), nullable=False, default="fr", comment="Langue préférée (fr=Français, en=English)"
    )

    # Statut
    is_active: Mapped[bool] = mapped_column(
        nullable=False, default=True, index=True, comment="Patient actif dans le système"
    )
    is_verified: Mapped[bool] = mapped_column(
        nullable=False, default=False, comment="Identité vérifiée par un professionnel"
    )

    # Métadonnées
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Date de création du profil",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Date de dernière modification",
    )
    created_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Keycloak user ID du créateur"
    )
    updated_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Keycloak user ID du dernier modificateur"
    )

    # Notes
    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Notes administratives (non médicales)"
    )

    def __repr__(self) -> str:
        """Représentation string du patient."""
        return f"<Patient(id={self.id}, name='{self.first_name} {self.last_name}')>"
