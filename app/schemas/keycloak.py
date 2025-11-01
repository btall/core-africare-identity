"""Schémas Pydantic pour les événements webhook Keycloak.

Ce module définit les schémas de validation pour les événements
reçus depuis Keycloak via webhooks pour synchronisation temps-réel.

Types d'événements supportés:
- REGISTER: Nouvel utilisateur enregistré
- UPDATE_PROFILE: Mise à jour du profil utilisateur
- UPDATE_EMAIL: Changement d'adresse email
- LOGIN: Connexion utilisateur (pour tracking)
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.utils import Email, NationalId, PhoneNumber


class KeycloakUserAttributes(BaseModel):
    """Attributs personnalisés de l'utilisateur Keycloak."""

    last_name: list[str] | None = Field(None, alias="lastName")
    first_name: list[str] | None = Field(None, alias="firstName")
    email: list[Email] | None = None
    username: list[str] | None = None
    phone: list[PhoneNumber] | None = None
    date_of_birth: list[date] | None = Field(None, alias="dateOfBirth")
    gender: list[str] | None = None
    national_id: list[NationalId] | None = None
    country: list[str] | None = None
    region: list[str] | None = None
    city: list[str] | None = None
    preferred_language: list[str] | None = None

    model_config = {
        "extra": "allow",  # Permet les attributs non définis
        "populate_by_name": True,  # Accepte snake_case et camelCase
    }


class KeycloakUser(BaseModel):
    """Représentation complète d'un utilisateur Keycloak (fusion de User et EventDetails)."""

    # Champs principaux de l'utilisateur
    id: str | None = Field(None, description="UUID de l'utilisateur Keycloak")
    username: str | None = Field(None, description="Nom d'utilisateur")
    email: str | None = Field(None, description="Adresse email")
    email_verified: bool = Field(
        default=False, alias="emailVerified", description="Email vérifié ou non"
    )
    first_name: str | None = Field(None, alias="firstName", description="Prénom")
    last_name: str | None = Field(None, alias="lastName", description="Nom de famille")
    enabled: bool = Field(default=True, description="Compte activé ou non")
    created_timestamp: int | None = Field(
        None, alias="createdTimestamp", description="Timestamp de création (ms depuis epoch)"
    )

    # Attributs personnalisés (peuvent venir de l'objet attributes ou directement de details)
    attributes: KeycloakUserAttributes | None = Field(
        None, description="Attributs personnalisés structurés"
    )

    # Attributs AfriCare (pour compatibilité avec details)
    phone: str | None = None
    date_of_birth: date | None = Field(None, alias="dateOfBirth", description="Date de naissance")
    gender: Literal["male", "female"] | None = None
    national_id: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    preferred_language: Literal["fr", "en"] | None = None

    model_config = {
        "extra": "allow",  # Permet les champs non définis
        "populate_by_name": True,  # Accepte snake_case et camelCase
    }


class KeycloakWebhookEvent(BaseModel):
    """Schéma principal pour un événement webhook Keycloak."""

    event_type: Literal[
        # Événements utilisateur normaux
        "REGISTER",
        "UPDATE_PROFILE",
        "UPDATE_EMAIL",
        "LOGIN",
        "VERIFY_EMAIL",
        "LOGOUT",
        # Événements admin console
        "ADMIN_UPDATE",
        "DELETE",
    ] = Field(..., alias="eventType", description="Type d'événement Keycloak")
    realm_id: str = Field(..., alias="realmId", description="Identifiant du realm Keycloak")
    client_id: str | None = Field(None, alias="clientId", description="Client Keycloak émetteur")
    user_id: str = Field(..., alias="userId", description="UUID de l'utilisateur Keycloak")

    # Métadonnées contextuelles
    ip_address: str | None = Field(
        None, alias="ipAddress", description="Adresse IP de l'utilisateur"
    )
    session_id: str | None = Field(None, alias="sessionId", description="Session ID Keycloak")

    # Objet utilisateur complet (pour événements REGISTER, UPDATE_PROFILE, etc.)
    # Contient toutes les données utilisateur (remplace l'ancien champ 'details')
    user: KeycloakUser | None = Field(
        None, description="Données complètes de l'utilisateur Keycloak"
    )

    # Timestamp (millisecondes depuis epoch)
    event_time: int = Field(
        ..., alias="eventTime", description="Timestamp de l'événement (ms depuis epoch)"
    )

    model_config = {"populate_by_name": True}  # Accepte à la fois snake_case et camelCase

    @field_validator("event_time")
    @classmethod
    def validate_event_time(cls, v: int) -> int:
        """Valide que le timestamp est raisonnable (derniers 30 jours ou futur proche).

        Fenêtre de 30 jours pour supporter:
        - Replay de messages Redis Streams après incident
        - Traitement de messages pending réclamés après downtime
        - Backlog d'événements accumulés pendant maintenance
        """
        now_ms = int(datetime.now().timestamp() * 1000)
        day_ms = 24 * 60 * 60 * 1000
        thirty_days_ms = 30 * day_ms

        # Accepte événements des derniers 30 jours ou jusqu'à 5min dans le futur (clock skew)
        five_minutes_ms = 5 * 60 * 1000  # 300000 ms
        if v < (now_ms - thirty_days_ms) or v > (now_ms + five_minutes_ms):
            raise ValueError(f"Timestamp invalide: {v} (maintenant: {now_ms})")

        return v

    @property
    def timestamp_datetime(self) -> datetime:
        """Convertit le timestamp (ms) en datetime Python."""
        return datetime.fromtimestamp(self.event_time / 1000)


class WebhookSignature(BaseModel):
    """Schéma pour la vérification de signature webhook."""

    signature: str = Field(..., description="Signature HMAC-SHA256 du payload")
    timestamp: str = Field(..., description="Timestamp de la requête webhook")

    @field_validator("signature")
    @classmethod
    def validate_signature_format(cls, v: str) -> str:
        """Valide le format de la signature (hexadécimal)."""
        if not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError("La signature doit être en format hexadécimal")
        if len(v) != 64:  # SHA256 = 64 caractères hex
            raise ValueError("La signature doit être de 64 caractères (SHA256)")
        return v


class WebhookVerificationResponse(BaseModel):
    """Réponse après vérification de signature webhook."""

    verified: bool = Field(..., description="True si la signature est valide")
    reason: str | None = Field(None, description="Raison de l'échec si non vérifié")


class SyncResult(BaseModel):
    """Résultat de la synchronisation d'un événement webhook."""

    success: bool = Field(..., description="True si synchronisation réussie")
    event_type: str = Field(..., description="Type d'événement traité")
    user_id: str = Field(..., description="UUID Keycloak de l'utilisateur")
    patient_id: int | None = Field(
        None, description="ID du patient créé/mis à jour (si applicable)"
    )
    message: str = Field(..., description="Message descriptif du résultat")
    synced_at: datetime = Field(
        default_factory=datetime.now, description="Timestamp de la synchronisation"
    )


class WebhookHealthCheck(BaseModel):
    """Schéma pour le health check du webhook endpoint."""

    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        ..., description="État de santé du webhook endpoint"
    )
    webhook_endpoint: str = Field(..., description="URL du webhook endpoint")
    last_event_received: datetime | None = Field(
        None, description="Timestamp du dernier événement reçu"
    )
    total_events_processed: int = Field(
        default=0, ge=0, description="Nombre total d'événements traités"
    )
    failed_events_count: int = Field(default=0, ge=0, description="Nombre d'événements en échec")
