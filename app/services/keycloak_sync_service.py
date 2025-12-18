"""Service de synchronisation des événements Keycloak vers HAPI FHIR + PostgreSQL.

Ce module implémente la logique de synchronisation temps-réel
entre les événements Keycloak et l'architecture hybride FHIR/PostgreSQL.

Architecture:
    Keycloak Webhook -> Redis Streams -> keycloak_sync_service
                                              |
                                              v
                              patient_service / professional_service
                                              |
                              +---------------+---------------+
                              |                               |
                              v                               v
                         HAPI FHIR                    PostgreSQL
                    (donnees demographiques)      (metadonnees GDPR)
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

import bcrypt
from keycloak import KeycloakAdmin
from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import publish
from app.core.exceptions import (
    AnonymizationError,
    KeycloakServiceError,
    ProfessionalDeletionBlockedError,
)
from app.core.retry import async_retry_with_backoff
from app.models.gdpr_metadata import PatientGdprMetadata, ProfessionalGdprMetadata

# Legacy imports pour les fonctions admin/scheduler qui utilisent encore les anciens modèles
# TODO: Migrer admin_patients.py et schedulers vers les services FHIR
from app.models.patient import Patient
from app.models.professional import Professional
from app.schemas.keycloak import KeycloakWebhookEvent, SyncResult
from app.schemas.patient import PatientCreate, PatientUpdate
from app.schemas.professional import ProfessionalCreate, ProfessionalUpdate
from app.services import patient_service, professional_service

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Client admin Keycloak pour récupérer les rôles utilisateur
# Note: Authentification via client credentials (service account)
keycloak_admin = KeycloakAdmin(
    server_url=settings.KEYCLOAK_SERVER_URL,
    realm_name=settings.KEYCLOAK_REALM,
    client_id=settings.KEYCLOAK_CLIENT_ID,
    client_secret_key=getattr(settings, "KEYCLOAK_CLIENT_SECRET", None),
    verify=True,
)

# Stratégies de suppression disponibles
DeletionStrategy = Literal["soft_delete", "hard_delete", "anonymize"]

# Exceptions DB transitoires qui déclenchent un retry
TRANSIENT_DB_EXCEPTIONS = (
    OperationalError,  # Connexion DB perdue, timeout, etc.
    DBAPIError,  # Erreurs DB génériques transitoires
)


async def get_user_roles_from_keycloak(user_id: str) -> list[str]:
    """
    Récupère les rôles d'un utilisateur depuis Keycloak.

    Cette fonction interroge Keycloak pour obtenir tous les rôles assignés
    à un utilisateur (realm roles et client roles).

    Args:
        user_id: UUID de l'utilisateur dans Keycloak

    Returns:
        Liste des rôles de l'utilisateur (ex: ["patient", "professional"])

    Raises:
        KeycloakServiceError: Si impossible de récupérer les rôles depuis Keycloak.
    """
    with tracer.start_as_current_span("get_user_roles_from_keycloak") as span:
        span.set_attribute("user.keycloak_id", user_id)

        try:
            # Récupérer les realm roles de l'utilisateur
            realm_roles = keycloak_admin.get_realm_roles_of_user(user_id)
            roles = [role["name"] for role in realm_roles]

            # Récupérer les client roles (si nécessaire)
            # Généralement les rôles patient/professional sont des realm roles
            client_id = keycloak_admin.get_client_id(settings.KEYCLOAK_CLIENT_ID)
            client_roles = keycloak_admin.get_client_roles_of_user(user_id, client_id)
            roles.extend([role["name"] for role in client_roles])

            # Dédupliquer
            roles = list(set(roles))

            span.set_attribute("user.roles", ",".join(roles))
            logger.info(f"Rôles récupérés pour user {user_id}: {roles}")

            return roles

        except Exception as e:
            logger.error(f"Erreur lors de la récupération des rôles Keycloak pour {user_id}: {e}")
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            # Lever une exception au lieu de retourner []
            raise KeycloakServiceError(
                detail=f"Cannot retrieve roles from Keycloak for user {user_id}: {e}",
                instance=f"/users/{user_id}/roles",
            ) from e


@async_retry_with_backoff(
    max_attempts=3,
    min_wait_seconds=1,
    max_wait_seconds=10,
    exceptions=TRANSIENT_DB_EXCEPTIONS,
)
async def sync_user_registration(db: AsyncSession, event: KeycloakWebhookEvent) -> SyncResult:
    """
    Synchronise un événement REGISTER (création d'utilisateur).

    Crée automatiquement un profil Patient ou Professional via les services FHIR:
    - Données démographiques dans HAPI FHIR
    - Métadonnées GDPR dans PostgreSQL

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak

    Returns:
        SyncResult avec les détails de la synchronisation
    """
    with tracer.start_as_current_span("sync_user_registration") as span:
        span.set_attribute("event.type", event.event_type)
        span.set_attribute("event.user_id", event.user_id)

        try:
            # Validation: l'objet user doit être présent
            if not event.user:
                logger.warning(f"Objet user manquant dans l'événement REGISTER: {event.user_id}")
                return SyncResult(
                    success=False,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="User object missing in event",
                )

            # Vérifier si l'utilisateur existe déjà (dans PatientGdprMetadata OU ProfessionalGdprMetadata)
            existing_patient = await db.execute(
                select(PatientGdprMetadata).where(
                    PatientGdprMetadata.keycloak_user_id == event.user_id
                )
            )
            existing_professional = await db.execute(
                select(ProfessionalGdprMetadata).where(
                    ProfessionalGdprMetadata.keycloak_user_id == event.user_id
                )
            )

            if existing_patient.scalar_one_or_none() or existing_professional.scalar_one_or_none():
                logger.info(f"Utilisateur déjà synchronisé: {event.user_id}")
                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="User already synchronized",
                )

            # Déterminer le type de profil selon les rôles Keycloak ET client_id
            # Priorité aux rôles Keycloak (source de vérité)
            # Fallback sur client_id si rôles non disponibles
            try:
                user_roles = await get_user_roles_from_keycloak(event.user_id)
                # Si le rôle "professional" est présent → Professional
                is_provider = "professional" in user_roles
                logger.info(
                    f"Type de profil déterminé par rôles Keycloak: "
                    f"roles={user_roles}, is_provider={is_provider}"
                )
            except KeycloakServiceError:
                # Fallback sur client_id si Keycloak indisponible
                logger.warning(
                    f"Impossible de récupérer les rôles Keycloak, "
                    f"fallback sur client_id: {event.client_id}"
                )
                is_provider = event.client_id == "apps-africare-provider-portal"

            if is_provider:
                # DETECT: Vérifier si professionnel revient après anonymisation
                email = event.user.email if event.user else None
                professional_id_str = None  # TODO: Extraire de user attributes si disponible

                if email:
                    returning_professional = await _check_returning_professional(
                        db, email, professional_id_str
                    )
                    if returning_professional:
                        logger.info(
                            f"Professionnel revenant détecté: {returning_professional.id} "
                            f"(correlation_hash={returning_professional.correlation_hash})"
                        )
                        # Publier événement de retour
                        await publish(
                            "identity.professional.returning_user",
                            {
                                "old_professional_id": returning_professional.id,
                                "new_keycloak_user_id": event.user_id,
                                "correlation_hash": returning_professional.correlation_hash,
                                "old_soft_deleted_at": (
                                    returning_professional.soft_deleted_at.isoformat()
                                    if returning_professional.soft_deleted_at
                                    else None
                                ),
                                "old_anonymized_at": (
                                    returning_professional.anonymized_at.isoformat()
                                    if returning_professional.anonymized_at
                                    else None
                                ),
                                "detected_at": datetime.now(UTC).isoformat(),
                            },
                        )

                # Créer un profil Professional via le service FHIR
                # (commit + publication événement inclus dans le service)
                professional_id = await _create_professional_from_event(db, event)

                span.set_attribute("professional.id", professional_id)
                span.set_attribute("client.id", event.client_id or "unknown")
                logger.info(
                    f"Professional créé depuis Keycloak via FHIR: professional_id={professional_id}, "
                    f"client_id={event.client_id}"
                )

                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=professional_id,  # Utilise patient_id pour compatibilité avec le schema
                    message=f"Professional created: {professional_id}",
                )

            # DETECT: Vérifier si patient revient après anonymisation
            email = event.user.email if event.user else None
            national_id = None  # TODO: Extraire de user attributes si disponible

            if email:
                returning_patient = await _check_returning_patient(db, email, national_id)
                if returning_patient:
                    logger.info(
                        f"Patient revenant détecté: {returning_patient.id} "
                        f"(correlation_hash={returning_patient.correlation_hash})"
                    )
                    # Publier événement de retour
                    await publish(
                        "identity.patient.returning_user",
                        {
                            "old_patient_id": returning_patient.id,
                            "new_keycloak_user_id": event.user_id,
                            "correlation_hash": returning_patient.correlation_hash,
                            "old_soft_deleted_at": (
                                returning_patient.soft_deleted_at.isoformat()
                                if returning_patient.soft_deleted_at
                                else None
                            ),
                            "old_anonymized_at": (
                                returning_patient.anonymized_at.isoformat()
                                if returning_patient.anonymized_at
                                else None
                            ),
                            "detected_at": datetime.now(UTC).isoformat(),
                        },
                    )

            # Créer un profil Patient via le service FHIR
            # (commit + publication événement inclus dans le service)
            patient_id = await _create_patient_from_event(db, event)

            span.set_attribute("patient.id", patient_id)
            span.set_attribute("client.id", event.client_id or "unknown")
            logger.info(
                f"Patient créé depuis Keycloak via FHIR: patient_id={patient_id}, "
                f"client_id={event.client_id}"
            )

            return SyncResult(
                success=True,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=patient_id,
                message=f"Patient created: {patient_id}",
            )

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            logger.error(f"Erreur lors de la synchronisation REGISTER: {e}")
            await db.rollback()
            raise


@async_retry_with_backoff(
    max_attempts=3,
    min_wait_seconds=1,
    max_wait_seconds=10,
    exceptions=TRANSIENT_DB_EXCEPTIONS,
)
async def sync_profile_update(db: AsyncSession, event: KeycloakWebhookEvent) -> SyncResult:
    """
    Synchronise un événement UPDATE_PROFILE via les services FHIR.

    Met à jour le profil Patient/Professional dans HAPI FHIR + PostgreSQL.

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak

    Returns:
        SyncResult avec les détails de la synchronisation
    """
    with tracer.start_as_current_span("sync_profile_update") as span:
        span.set_attribute("event.type", event.event_type)
        span.set_attribute("event.user_id", event.user_id)

        try:
            # Validation: l'objet user doit être présent
            if not event.user:
                logger.warning(
                    f"Objet user manquant dans l'événement UPDATE_PROFILE: {event.user_id}"
                )
                return SyncResult(
                    success=False,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="User object missing in event",
                )

            # Chercher d'abord dans PatientGdprMetadata
            result = await db.execute(
                select(PatientGdprMetadata).where(
                    PatientGdprMetadata.keycloak_user_id == event.user_id
                )
            )
            patient_gdpr = result.scalar_one_or_none()

            # Si pas trouvé dans Patient, chercher dans ProfessionalGdprMetadata
            professional_gdpr = None
            if not patient_gdpr:
                result = await db.execute(
                    select(ProfessionalGdprMetadata).where(
                        ProfessionalGdprMetadata.keycloak_user_id == event.user_id
                    )
                )
                professional_gdpr = result.scalar_one_or_none()

            # Si ni Patient ni Professional trouvé, retourner erreur
            if not patient_gdpr and not professional_gdpr:
                logger.warning(
                    f"Aucun Patient ou Professional trouvé pour user_id: {event.user_id}"
                )
                return SyncResult(
                    success=False,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="Patient or Professional not found",
                )

            # Construire les données de mise à jour
            updated_fields = []
            update_data = {}

            if event.user.first_name:
                update_data["first_name"] = event.user.first_name
                updated_fields.append("first_name")

            if event.user.last_name:
                update_data["last_name"] = event.user.last_name
                updated_fields.append("last_name")

            if event.user.phone:
                update_data["phone"] = event.user.phone
                updated_fields.append("phone")

            if not update_data:
                # Aucun champ à mettre à jour
                profile_id = patient_gdpr.id if patient_gdpr else professional_gdpr.id
                profile_type = "patient" if patient_gdpr else "professional"
                span.set_attribute(f"{profile_type}.id", profile_id)
                span.set_attribute("updated_fields", "[]")

                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=profile_id,
                    message="No changes",
                )

            if patient_gdpr:
                # Mettre à jour Patient via le service FHIR
                patient_update = PatientUpdate(**update_data)
                updated_response = await patient_service.update_patient(
                    db=db,
                    patient_id=patient_gdpr.id,
                    patient_update=patient_update,
                    current_user_id=event.user_id,
                )

                if not updated_response:
                    return SyncResult(
                        success=False,
                        event_type=event.event_type,
                        user_id=event.user_id,
                        patient_id=patient_gdpr.id,
                        message="Patient update failed",
                    )

                span.set_attribute("patient.id", patient_gdpr.id)
                span.set_attribute("updated_fields", str(updated_fields))
                logger.info(
                    f"Patient mis à jour via FHIR: patient_id={patient_gdpr.id}, "
                    f"fields={updated_fields}"
                )

                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=patient_gdpr.id,
                    message=f"Updated fields: {updated_fields}",
                )

            else:
                # Mettre à jour Professional via le service FHIR
                professional_update = ProfessionalUpdate(**update_data)
                updated_response = await professional_service.update_professional(
                    db=db,
                    professional_id=professional_gdpr.id,
                    professional_update=professional_update,
                    current_user_id=event.user_id,
                )

                if not updated_response:
                    return SyncResult(
                        success=False,
                        event_type=event.event_type,
                        user_id=event.user_id,
                        patient_id=professional_gdpr.id,
                        message="Professional update failed",
                    )

                span.set_attribute("professional.id", professional_gdpr.id)
                span.set_attribute("updated_fields", str(updated_fields))
                logger.info(
                    f"Professional mis à jour via FHIR: professional_id={professional_gdpr.id}, "
                    f"fields={updated_fields}"
                )

                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=professional_gdpr.id,
                    message=f"Updated fields: {updated_fields}",
                )

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            logger.error(f"Erreur lors de la synchronisation UPDATE_PROFILE: {e}")
            await db.rollback()
            raise


@async_retry_with_backoff(
    max_attempts=3,
    min_wait_seconds=1,
    max_wait_seconds=10,
    exceptions=TRANSIENT_DB_EXCEPTIONS,
)
async def sync_email_update(db: AsyncSession, event: KeycloakWebhookEvent) -> SyncResult:
    """
    Synchronise un événement UPDATE_EMAIL via les services FHIR.

    Met à jour l'adresse email du Patient/Professional dans HAPI FHIR + PostgreSQL.

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak

    Returns:
        SyncResult avec les détails de la synchronisation
    """
    with tracer.start_as_current_span("sync_email_update") as span:
        span.set_attribute("event.type", event.event_type)
        span.set_attribute("event.user_id", event.user_id)

        try:
            # Validation: l'objet user doit être présent
            if not event.user:
                logger.warning(
                    f"Objet user manquant dans l'événement UPDATE_EMAIL: {event.user_id}"
                )
                return SyncResult(
                    success=False,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="User object missing in event",
                )

            new_email = event.user.email
            if not new_email:
                logger.warning("Email manquant dans l'événement UPDATE_EMAIL")
                return SyncResult(
                    success=False,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="Email missing in event",
                )

            # Chercher d'abord dans PatientGdprMetadata
            result = await db.execute(
                select(PatientGdprMetadata).where(
                    PatientGdprMetadata.keycloak_user_id == event.user_id
                )
            )
            patient_gdpr = result.scalar_one_or_none()

            # Si pas trouvé dans Patient, chercher dans ProfessionalGdprMetadata
            professional_gdpr = None
            if not patient_gdpr:
                result = await db.execute(
                    select(ProfessionalGdprMetadata).where(
                        ProfessionalGdprMetadata.keycloak_user_id == event.user_id
                    )
                )
                professional_gdpr = result.scalar_one_or_none()

            # Si ni Patient ni Professional trouvé, retourner erreur
            if not patient_gdpr and not professional_gdpr:
                logger.warning(
                    f"Aucun Patient ou Professional trouvé pour user_id: {event.user_id}"
                )
                return SyncResult(
                    success=False,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="Patient or Professional not found",
                )

            if patient_gdpr:
                # Mettre à jour l'email via le service FHIR + is_verified localement
                patient_update = PatientUpdate(email=new_email)
                updated_response = await patient_service.update_patient(
                    db=db,
                    patient_id=patient_gdpr.id,
                    patient_update=patient_update,
                    current_user_id=event.user_id,
                )

                if not updated_response:
                    return SyncResult(
                        success=False,
                        event_type=event.event_type,
                        user_id=event.user_id,
                        patient_id=patient_gdpr.id,
                        message="Patient email update failed",
                    )

                # Mettre à jour is_verified localement (champ GDPR)
                patient_gdpr.is_verified = event.user.email_verified or False
                patient_gdpr.updated_at = datetime.now(UTC)
                patient_gdpr.updated_by = event.user_id
                await db.commit()

                span.set_attribute("patient.id", patient_gdpr.id)
                span.set_attribute("email.new", new_email)
                logger.info(
                    f"Email Patient mis à jour via FHIR: patient_id={patient_gdpr.id}, "
                    f"email={new_email}, verified={patient_gdpr.is_verified}"
                )

                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=patient_gdpr.id,
                    message=f"Email updated: {new_email}",
                )

            else:
                # Mettre à jour l'email via le service FHIR + is_verified localement
                professional_update = ProfessionalUpdate(email=new_email)
                updated_response = await professional_service.update_professional(
                    db=db,
                    professional_id=professional_gdpr.id,
                    professional_update=professional_update,
                    current_user_id=event.user_id,
                )

                if not updated_response:
                    return SyncResult(
                        success=False,
                        event_type=event.event_type,
                        user_id=event.user_id,
                        patient_id=professional_gdpr.id,
                        message="Professional email update failed",
                    )

                # Mettre à jour is_verified localement (champ GDPR)
                professional_gdpr.is_verified = event.user.email_verified or False
                professional_gdpr.updated_at = datetime.now(UTC)
                professional_gdpr.updated_by = event.user_id
                await db.commit()

                span.set_attribute("professional.id", professional_gdpr.id)
                span.set_attribute("email.new", new_email)
                logger.info(
                    f"Email Professional mis à jour via FHIR: professional_id={professional_gdpr.id}, "
                    f"email={new_email}, verified={professional_gdpr.is_verified}"
                )

                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=professional_gdpr.id,
                    message=f"Email updated: {new_email}",
                )

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            logger.error(f"Erreur lors de la synchronisation UPDATE_EMAIL: {e}")
            await db.rollback()
            raise


async def track_user_login(db: AsyncSession, event: KeycloakWebhookEvent) -> SyncResult:
    """
    Track un événement LOGIN pour analytics.

    Note: N'effectue pas de modifications dans la DB, seulement du logging/tracking.

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak

    Returns:
        SyncResult avec les détails du tracking
    """
    with tracer.start_as_current_span("track_user_login") as span:
        span.set_attribute("event.type", event.event_type)
        span.set_attribute("event.user_id", event.user_id)
        span.set_attribute("ip_address", event.ip_address or "unknown")

        try:
            # Publier événement pour analytics/audit
            await publish(
                "identity.user.login",
                {
                    "keycloak_user_id": event.user_id,
                    "ip_address": event.ip_address,
                    "session_id": event.session_id,
                    "timestamp": event.timestamp_datetime.isoformat(),
                },
            )

            logger.info(
                f"Login tracked: user_id={event.user_id}, "
                f"ip={event.ip_address}, session={event.session_id}"
            )

            return SyncResult(
                success=True,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=None,
                message="Login tracked",
            )

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            logger.error(f"Erreur lors du tracking LOGIN: {e}")
            raise


async def _create_patient_from_event(db: AsyncSession, event: KeycloakWebhookEvent) -> int:
    """
    Crée un Patient via le service FHIR depuis un événement Keycloak.

    Cette fonction utilise patient_service.create_patient() qui:
    1. Crée la ressource Patient dans HAPI FHIR
    2. Crée les métadonnées GDPR dans PostgreSQL
    3. Publie l'événement identity.patient.created

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak

    Returns:
        ID numérique du patient créé

    Raises:
        ValueError: Si données requises manquantes
        FHIROperationError: Si création FHIR échoue
    """
    if not event.user:
        raise ValueError("Objet user manquant dans l'événement")

    user = event.user

    # Validation des champs requis
    if not user.first_name or not user.last_name:
        raise ValueError("first_name et last_name sont requis")

    if user.date_of_birth is None:
        raise ValueError("date_of_birth est requis")

    if not user.gender:
        raise ValueError("gender est requis")

    # Construire le schéma PatientCreate
    patient_data = PatientCreate(
        keycloak_user_id=event.user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        date_of_birth=user.date_of_birth,
        gender=user.gender,
        email=user.email,
        phone=user.phone,
        national_id=user.national_id,
        country=user.country or "Sénégal",
        region=user.region,
        city=user.city,
        preferred_language=user.preferred_language or "fr",
    )

    # Créer via le service FHIR (commit + publication événement inclus)
    patient_response = await patient_service.create_patient(
        db=db,
        patient_data=patient_data,
        current_user_id=event.user_id,  # L'utilisateur se crée lui-même
    )

    return patient_response.id


async def _create_professional_from_event(db: AsyncSession, event: KeycloakWebhookEvent) -> int:
    """
    Crée un Professional via le service FHIR depuis un événement Keycloak.

    Cette fonction utilise professional_service.create_professional() qui:
    1. Crée la ressource Practitioner dans HAPI FHIR
    2. Crée les métadonnées GDPR dans PostgreSQL
    3. Publie l'événement identity.professional.created

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak

    Returns:
        ID numérique du professionnel créé

    Raises:
        ValueError: Si données requises manquantes
        FHIROperationError: Si création FHIR échoue
    """
    if not event.user:
        raise ValueError("Objet user manquant dans l'événement")

    user = event.user

    # Validation des champs requis
    if not user.first_name or not user.last_name:
        raise ValueError("first_name et last_name sont requis")

    if not user.email:
        raise ValueError("email est requis pour un professionnel")

    # Construire le schéma ProfessionalCreate avec valeurs par défaut
    # Note: Le profil devra être complété lors de l'onboarding
    professional_data = ProfessionalCreate(
        keycloak_user_id=event.user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        title="Dr",  # Valeur par défaut, à compléter lors de l'onboarding
        specialty="Non spécifié",  # À compléter lors de l'onboarding
        professional_type="other",  # À compléter lors de l'onboarding
        email=user.email,
        phone=user.phone or "+221000000000",  # Valeur par défaut si non fourni
        languages_spoken=user.preferred_language or "fr",
        is_available=False,  # Pas disponible tant que le profil n'est pas complet
    )

    # Créer via le service FHIR (commit + publication événement inclus)
    professional_response = await professional_service.create_professional(
        db=db,
        professional_data=professional_data,
        current_user_id=event.user_id,  # L'utilisateur se crée lui-même
    )

    return professional_response.id


################################################################################
# Fonctions de suppression d'utilisateur (DELETE event)
################################################################################


def _generate_correlation_hash(email: str, professional_id: str | None) -> str:
    """
    Génère un hash de corrélation SHA-256 déterministe pour détecter retours après anonymisation.

    Le hash est calculé à partir de email + professional_id + salt global, permettant
    de détecter si un professionnel revient après anonymisation sans stocker les données
    personnelles en clair (conformité RGPD).

    Args:
        email: Email du professionnel avant anonymisation
        professional_id: Numéro d'ordre professionnel (peut être None)

    Returns:
        Hash SHA-256 hexadécimal (64 caractères)

    Example:
        >>> hash = _generate_correlation_hash("dr.diop@hospital.sn", "CNOM12345")
        >>> len(hash)
        64
    """
    import hashlib

    from app.core.config import settings

    # Salt global depuis configuration (ou défaut si non défini)
    salt = getattr(settings, "CORRELATION_HASH_SALT", "africare-identity-salt-v1")

    # Construire la chaîne à hasher
    hash_input = f"{email}|{professional_id or ''}|{salt}"

    # Générer SHA-256
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()


async def _check_returning_professional(
    db: AsyncSession, email: str, professional_id: str | None
) -> ProfessionalGdprMetadata | None:
    """
    Vérifie si un professionnel anonymisé revient en calculant son correlation_hash.

    Cette fonction permet de détecter les professionnels qui reviennent après suppression
    en comparant le hash calculé avec ceux stockés dans les métadonnées GDPR.

    Args:
        db: Session de base de données async
        email: Email du nouveau professionnel
        professional_id: Numéro d'ordre professionnel (peut être None)

    Returns:
        Métadonnées GDPR du professionnel anonymisé correspondant si trouvé, None sinon

    Example:
        ```python
        returning = await _check_returning_professional(db, "dr.diop@hospital.sn", "CNOM12345")
        if returning:
            logger.info(f"Professionnel revenant détecté: {returning.id}")
        ```
    """
    # Générer le hash pour ce professionnel
    correlation_hash = _generate_correlation_hash(email, professional_id)

    # Chercher dans les métadonnées GDPR (uniquement anonymisés)
    result = await db.execute(
        select(ProfessionalGdprMetadata).where(
            ProfessionalGdprMetadata.correlation_hash == correlation_hash,
            ProfessionalGdprMetadata.anonymized_at.isnot(None),  # Seulement les anonymisés
        )
    )
    return result.scalar_one_or_none()


def _generate_patient_correlation_hash(email: str, national_id: str | None = None) -> str:
    """
    Génère un hash de corrélation SHA-256 déterministe pour détecter retours après anonymisation.

    Le hash est calculé à partir de email + national_id + salt global, permettant
    de détecter si un patient revient après anonymisation sans stocker les données
    personnelles en clair (conformité RGPD).

    Args:
        email: Email du patient avant anonymisation
        national_id: Numéro d'identification nationale (CNI, passeport) - peut être None

    Returns:
        Hash SHA-256 hexadécimal (64 caractères)

    Example:
        >>> hash = _generate_patient_correlation_hash("amadou@email.sn", "CNI123456")
        >>> len(hash)
        64
    """
    import hashlib

    from app.core.config import settings

    # Salt global depuis configuration (ou défaut si non défini)
    salt = getattr(settings, "CORRELATION_HASH_SALT", "africare-identity-salt-v1")

    # Construire la chaîne à hasher
    hash_input = f"{email}|{national_id or ''}|{salt}"

    # Générer SHA-256
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()


async def _check_returning_patient(
    db: AsyncSession, email: str, national_id: str | None = None
) -> PatientGdprMetadata | None:
    """
    Vérifie si un patient anonymisé revient en calculant son correlation_hash.

    Cette fonction permet de détecter les patients qui reviennent après suppression
    en comparant le hash calculé avec ceux stockés dans les métadonnées GDPR.

    Args:
        db: Session de base de données async
        email: Email du nouveau patient
        national_id: Numéro d'identification nationale (peut être None)

    Returns:
        Métadonnées GDPR du patient anonymisé correspondant si trouvé, None sinon

    Example:
        ```python
        returning = await _check_returning_patient(db, "amadou@email.sn", "CNI123456")
        if returning:
            logger.info(f"Patient revenant détecté: {returning.id}")
        ```
    """
    # Générer le hash pour ce patient
    correlation_hash = _generate_patient_correlation_hash(email, national_id)

    # Chercher dans les métadonnées GDPR (uniquement anonymisés)
    result = await db.execute(
        select(PatientGdprMetadata).where(
            PatientGdprMetadata.correlation_hash == correlation_hash,
            PatientGdprMetadata.anonymized_at.isnot(None),  # Seulement les anonymisés
        )
    )
    return result.scalar_one_or_none()


@async_retry_with_backoff(
    max_attempts=3,
    min_wait_seconds=1,
    max_wait_seconds=10,
    exceptions=TRANSIENT_DB_EXCEPTIONS,
)
async def sync_user_deletion(
    db: AsyncSession, event: KeycloakWebhookEvent, strategy: DeletionStrategy = "soft_delete"
) -> SyncResult:
    """
    Synchronise un événement DELETE via les services FHIR.

    Logique basée sur les rôles:
    - Si rôle "professional" → désactive Professional (FHIR + local)
    - Si rôle "patient" → désactive Patient (FHIR + local)

    Stratégie par défaut: soft_delete (FHIR active=false + local soft_deleted_at)
    L'anonymisation définitive se fait après période de grâce (7 jours) via scheduler.

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak
        strategy: Stratégie de suppression (actuellement seul soft_delete supporté via FHIR)

    Returns:
        SyncResult avec les détails de la suppression
    """
    with tracer.start_as_current_span("sync_user_deletion") as span:
        span.set_attribute("event.type", event.event_type)
        span.set_attribute("event.user_id", event.user_id)
        span.set_attribute("deletion.strategy", strategy)

        try:
            # Récupérer les rôles de l'utilisateur depuis Keycloak
            # Fallback: si erreur, on cherche quand même dans les tables locales
            user_roles = await get_user_roles_from_keycloak(event.user_id)

            # Si pas de rôles récupérés, fallback sur détection via existence des profils
            if not user_roles:
                logger.warning(
                    f"Impossible de récupérer les rôles Keycloak pour {event.user_id}, "
                    "fallback sur détection via tables locales"
                )
                # Détecter les rôles via l'existence des métadonnées GDPR
                user_roles = []

                # Vérifier si profil professional existe
                result_prof_check = await db.execute(
                    select(ProfessionalGdprMetadata).where(
                        ProfessionalGdprMetadata.keycloak_user_id == event.user_id
                    )
                )
                if result_prof_check.scalar_one_or_none():
                    user_roles.append("professional")

                # Vérifier si profil patient existe
                result_patient_check = await db.execute(
                    select(PatientGdprMetadata).where(
                        PatientGdprMetadata.keycloak_user_id == event.user_id
                    )
                )
                if result_patient_check.scalar_one_or_none():
                    user_roles.append("patient")

            span.set_attribute("user.roles", ",".join(user_roles))

            has_professional_role = "professional" in user_roles
            has_patient_role = "patient" in user_roles

            logger.info(
                f"Suppression user {event.user_id}: "
                f"professional={has_professional_role}, patient={has_patient_role}"
            )

            deleted_tables = []
            patient_id = None
            professional_id = None
            deletion_reason = event.deletion_reason or "keycloak_account_deleted"

            # Si l'utilisateur a le rôle professional, désactiver le profil
            if has_professional_role:
                result_prof = await db.execute(
                    select(ProfessionalGdprMetadata).where(
                        ProfessionalGdprMetadata.keycloak_user_id == event.user_id,
                        ProfessionalGdprMetadata.soft_deleted_at.is_(None),
                    )
                )
                professional_gdpr = result_prof.scalar_one_or_none()

                if professional_gdpr:
                    professional_id = professional_gdpr.id
                    # Utiliser le service FHIR pour soft delete
                    deleted = await professional_service.delete_professional(
                        db=db,
                        professional_id=professional_id,
                        current_user_id=event.user_id,
                        deletion_reason=deletion_reason,
                    )
                    if deleted:
                        deleted_tables.append("professionals")
                        logger.info(f"Professional désactivé via FHIR: id={professional_id}")

            # Désactiver le profil patient
            if has_patient_role:
                result_patient = await db.execute(
                    select(PatientGdprMetadata).where(
                        PatientGdprMetadata.keycloak_user_id == event.user_id,
                        PatientGdprMetadata.soft_deleted_at.is_(None),
                    )
                )
                patient_gdpr = result_patient.scalar_one_or_none()

                if patient_gdpr:
                    patient_id = patient_gdpr.id
                    # Utiliser le service FHIR pour soft delete
                    deleted = await patient_service.delete_patient(
                        db=db,
                        patient_id=patient_id,
                        current_user_id=event.user_id,
                        deletion_reason=deletion_reason,
                    )
                    if deleted:
                        deleted_tables.append("patients")
                        logger.info(f"Patient désactivé via FHIR: id={patient_id}")

            if not deleted_tables:
                logger.warning(
                    f"Aucun profil trouvé pour user_id: {event.user_id} (roles: {user_roles})"
                )
                return SyncResult(
                    success=False,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message=f"No profile found for user (roles: {user_roles})",
                )

            # Publier événement de suppression global pour les autres services
            await publish(
                "identity.user.deleted",
                {
                    "keycloak_user_id": event.user_id,
                    "patient_id": patient_id,
                    "professional_id": professional_id,
                    "deletion_strategy": strategy,
                    "deleted_tables": deleted_tables,
                    "user_roles": user_roles,
                    "deleted_at": datetime.now(UTC).isoformat(),
                    "reason": deletion_reason,
                },
            )

            span.set_attribute("deletion.patient_id", patient_id or "none")
            span.set_attribute("deletion.professional_id", professional_id or "none")
            span.set_attribute("deletion.tables", ",".join(deleted_tables))

            message = f"User deactivated in {', '.join(deleted_tables)} via FHIR"

            return SyncResult(
                success=True,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=patient_id,
                message=message,
            )

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            logger.error(f"Erreur lors de la synchronisation DELETE: {e}")
            await db.rollback()
            raise


async def _apply_deletion_strategy(
    db: AsyncSession,
    entity: Patient | Professional,
    event: KeycloakWebhookEvent,
    strategy: DeletionStrategy,
    entity_type: Literal["patient", "professional"],
) -> None:
    """
    Applique la stratégie de suppression sur une entité (Patient ou Professional).

    Args:
        db: Session de base de données
        entity: Instance Patient ou Professional à supprimer
        event: Événement webhook Keycloak
        strategy: Stratégie de suppression
        entity_type: Type d'entité ("patient" ou "professional")
    """
    if strategy == "soft_delete":
        await _soft_delete(entity, event)
    elif strategy == "anonymize":
        await _anonymize(entity, event, entity_type)
    elif strategy == "hard_delete":
        await _hard_delete(db, entity)
    else:
        raise ValueError(f"Unknown deletion strategy: {strategy}")


async def _soft_delete(entity: Patient | Professional, event: KeycloakWebhookEvent) -> None:
    """
    Soft delete avec période de grâce de 7 jours.

    Workflow:
    1. Vérifie si professional/patient sous enquête (bloque si true)
    2. Génère correlation_hash AVANT anonymisation (pour détection retours)
    3. Marque comme inactif avec soft_deleted_at
    4. Anonymisation effective après 7 jours (scheduler)

    Raises:
        ProfessionalDeletionBlockedError: Si professional.under_investigation=True
        PatientDeletionBlockedError: Si patient.under_investigation=True
    """
    from datetime import UTC

    from app.core.exceptions import PatientDeletionBlockedError

    # CHECK: Bloquer si entité sous enquête
    if hasattr(entity, "under_investigation") and entity.under_investigation:
        entity_type = "Professional" if isinstance(entity, Professional) else "Patient"
        logger.error(
            f"Soft delete bloqué pour {entity_type} {entity.id}: under_investigation=True",
            extra={"investigation_notes": entity.investigation_notes},
        )

        # Lever exception spécifique selon le type
        if isinstance(entity, Professional):
            raise ProfessionalDeletionBlockedError(
                professional_id=entity.id,
                reason="under_investigation",
                investigation_notes=entity.investigation_notes,
            )
        else:  # Patient
            raise PatientDeletionBlockedError(
                patient_id=entity.id,
                reason="under_investigation",
                investigation_notes=entity.investigation_notes,
            )

    # CHECK: Déjà soft deleted ou anonymisé
    if hasattr(entity, "soft_deleted_at") and entity.soft_deleted_at is not None:
        logger.warning(f"{entity.__class__.__name__} {entity.id} already soft deleted")
        return
    if hasattr(entity, "anonymized_at") and entity.anonymized_at is not None:
        logger.warning(f"{entity.__class__.__name__} {entity.id} already anonymized")
        return

    # STEP 1: Générer correlation_hash AVANT anonymisation
    if not entity.correlation_hash:
        if isinstance(entity, Professional):
            entity.correlation_hash = _generate_correlation_hash(
                entity.email, entity.professional_id
            )
            logger.info(
                f"Generated correlation_hash for Professional {entity.id}",
                extra={"correlation_hash": entity.correlation_hash},
            )
        elif isinstance(entity, Patient):
            entity.correlation_hash = _generate_patient_correlation_hash(
                entity.email, entity.national_id
            )
            logger.info(
                f"Generated correlation_hash for Patient {entity.id}",
                extra={"correlation_hash": entity.correlation_hash},
            )

    # STEP 2: Soft delete avec période de grâce
    now = datetime.now(UTC)
    entity.is_active = False
    entity.soft_deleted_at = now
    entity.deletion_reason = event.deletion_reason or "user_request"
    entity.updated_at = now

    logger.info(
        f"Soft delete {entity.__class__.__name__}: {entity.id} (grace period: 7 days)",
        extra={
            "soft_deleted_at": now.isoformat(),
            "anonymization_scheduled": (now + timedelta(days=7)).isoformat(),
        },
    )

    # STEP 3: Publier événement de soft deletion
    entity_type_str = "professional" if isinstance(entity, Professional) else "patient"
    await publish(
        f"identity.{entity_type_str}.soft_deleted",
        {
            f"{entity_type_str}_keycloak_id": entity.keycloak_user_id,
            "deleted_at": now.isoformat(),
            "reason": entity.deletion_reason,
            "anonymization_scheduled_at": (now + timedelta(days=7)).isoformat(),
        },
    )


async def _anonymize(
    entity: Patient | Professional,
    event: KeycloakWebhookEvent,
    entity_type: Literal["patient", "professional"],
) -> None:
    """
    Anonymisation RGPD: Hash les données personnelles avec bcrypt.

    Préserve:
    - ID (pour relations avec autres services)
    - Date de naissance / années d'expérience (pour statistiques)
    - Genre / spécialité (pour statistiques médicales)
    - Dates de création/modification (audit)

    Anonymise (hashed avec bcrypt):
    - Prénom/Nom (hashés de manière irréversible)
    - Email (hashé)
    - Téléphone (supprimé)
    - Adresse (supprimée)
    - GPS (pour patients, supprimé)
    - Contact d'urgence (supprimé)
    - Identifiants nationaux (supprimés)

    Raises:
        AnonymizationError: Si le hashing bcrypt échoue.
    """
    entity_id = entity.id

    try:
        # Générer un salt unique pour chaque valeur
        salt = bcrypt.gensalt()

        # Hasher les données sensibles avec bcrypt (irréversible)
        entity.first_name = bcrypt.hashpw(f"ANONYME_{entity_id}".encode(), salt).decode("utf-8")
        entity.last_name = bcrypt.hashpw(
            f"{entity_type.upper()}_{entity_id}".encode(), salt
        ).decode("utf-8")
        entity.email = bcrypt.hashpw(f"deleted_{entity_id}@anonymized.local".encode(), salt).decode(
            "utf-8"
        )
        # Phone est NOT NULL pour Professional, utiliser placeholder
        entity.phone = "+ANONYMIZED"
    except Exception as e:
        logger.error(f"Échec du hashing bcrypt pour {entity_type} {entity_id}: {e}")
        raise AnonymizationError(
            detail=f"Failed to anonymize {entity_type} {entity_id}: bcrypt hashing failed",
            instance=f"/{entity_type}s/{entity_id}/anonymize",
        ) from e

    # Données spécifiques aux patients
    if isinstance(entity, Patient):
        entity.phone_secondary = None
        entity.national_id = None
        entity.address_line1 = None
        entity.address_line2 = None
        entity.city = None
        entity.region = None
        entity.postal_code = None
        entity.latitude = None
        entity.longitude = None
        entity.emergency_contact_name = None
        entity.emergency_contact_phone = None
        entity.notes = "[DONNEES ANONYMISEES CONFORMEMENT RGPD]"

    # Données spécifiques aux professionnels
    if isinstance(entity, Professional):
        entity.phone_secondary = None
        entity.professional_id = None
        entity.facility_name = None
        entity.facility_address = None
        entity.facility_city = None
        entity.facility_region = None
        entity.qualifications = "[DONNEES ANONYMISEES CONFORMEMENT RGPD]"
        entity.notes = "[DONNEES ANONYMISEES CONFORMEMENT RGPD]"
        entity.digital_signature = None

    # Marquer comme inactif et supprimé
    entity.is_active = False
    entity.deleted_at = datetime.now()
    entity.deleted_by = event.user_id
    entity.deletion_reason = "gdpr_compliance"
    entity.updated_at = datetime.now()

    logger.info(f"{entity.__class__.__name__} anonymisé: {entity_id}")

    # Publier événement d'anonymisation
    await publish(
        f"identity.{entity_type}.anonymized",
        {
            f"{entity_type}_keycloak_id": entity.keycloak_user_id,
            "anonymized_at": datetime.now().isoformat(),
            "deletion_type": "anonymize",
        },
    )


def _anonymize_entity(entity: Patient | Professional) -> None:
    """
    Anonymise une entité (Patient ou Professional) sans événement Keycloak.

    Version simplifiée de _anonymize() pour usage par le scheduler.
    Utilisée par anonymization_scheduler pour anonymiser après période de grâce.

    Args:
        entity: Instance Patient ou Professional à anonymiser

    Raises:
        AnonymizationError: Si le hashing bcrypt échoue
    """
    from datetime import UTC

    entity_id = entity.id
    entity_type = "professional" if isinstance(entity, Professional) else "patient"

    try:
        # Générer un salt unique pour chaque valeur
        salt = bcrypt.gensalt()

        # Hasher les données sensibles avec bcrypt (irréversible)
        entity.first_name = bcrypt.hashpw(f"ANONYME_{entity_id}".encode(), salt).decode("utf-8")
        entity.last_name = bcrypt.hashpw(
            f"{entity_type.upper()}_{entity_id}".encode(), salt
        ).decode("utf-8")
        entity.email = bcrypt.hashpw(f"deleted_{entity_id}@anonymized.local".encode(), salt).decode(
            "utf-8"
        )
        # Phone est NOT NULL pour Professional, utiliser placeholder
        entity.phone = "+ANONYMIZED"
    except Exception as e:
        logger.error(f"Échec du hashing bcrypt pour {entity_type} {entity_id}: {e}")
        raise AnonymizationError(
            detail=f"Failed to anonymize {entity_type} {entity_id}: bcrypt hashing failed",
            instance=f"/{entity_type}s/{entity_id}/anonymize",
        ) from e

    # Données spécifiques aux patients
    if isinstance(entity, Patient):
        entity.phone_secondary = None
        entity.national_id = None
        entity.address_line1 = None
        entity.address_line2 = None
        entity.city = None
        entity.region = None
        entity.postal_code = None
        entity.latitude = None
        entity.longitude = None
        entity.emergency_contact_name = None
        entity.emergency_contact_phone = None
        entity.notes = "[DONNEES ANONYMISEES CONFORMEMENT RGPD]"

    # Données spécifiques aux professionnels
    if isinstance(entity, Professional):
        entity.phone_secondary = None
        entity.professional_id = None
        entity.facility_name = None
        entity.facility_address = None
        entity.facility_city = None
        entity.facility_region = None
        entity.qualifications = "[DONNEES ANONYMISEES CONFORMEMENT RGPD]"
        entity.notes = "[DONNEES ANONYMISEES CONFORMEMENT RGPD]"
        entity.digital_signature = None

    # Marquer comme inactif (déjà fait par soft_delete, mais par sécurité)
    entity.is_active = False
    entity.updated_at = datetime.now(UTC)

    logger.info(f"{entity.__class__.__name__} anonymisé: {entity_id}")


async def _hard_delete(db: AsyncSession, entity: Patient | Professional) -> None:
    """
    Hard delete: Suppression physique de l'entité.

    ATTENTION: Cette méthode supprime définitivement toutes les données.
    À utiliser uniquement dans des contextes non-médicaux ou après anonymisation
    des données médicales dans les autres services.
    """
    from datetime import UTC

    entity_id = entity.id
    entity_type = entity.__class__.__name__
    entity_type_str = "professional" if isinstance(entity, Professional) else "patient"

    # Publier événement avant la suppression physique
    await publish(
        f"identity.{entity_type_str}.deleted",
        {
            f"{entity_type_str}_keycloak_id": entity.keycloak_user_id,
            "deleted_at": datetime.now(UTC).isoformat(),
            "deletion_type": "hard",
        },
    )

    await db.delete(entity)
    logger.warning(f"Hard delete {entity_type}: {entity_id}")
