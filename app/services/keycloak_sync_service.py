"""Service de synchronisation des événements Keycloak vers PostgreSQL.

Ce module implémente la logique de synchronisation temps-réel
entre les événements Keycloak et la base de données locale.
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
from app.models.patient import Patient
from app.models.professional import Professional
from app.schemas.keycloak import KeycloakWebhookEvent, SyncResult

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

    Crée automatiquement un profil Patient ou Professional dans PostgreSQL
    basé sur les attributs Keycloak.

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

            # Vérifier si l'utilisateur existe déjà (dans Patient OU Professional)
            existing_patient = await db.execute(
                select(Patient).where(Patient.keycloak_user_id == event.user_id)
            )
            existing_professional = await db.execute(
                select(Professional).where(Professional.keycloak_user_id == event.user_id)
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
                professional_id = None  # TODO: Extraire de user attributes si disponible

                if email:
                    returning_professional = await _check_returning_professional(
                        db, email, professional_id
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

                # Créer un profil Professional
                professional = await _create_professional_from_event(db, event)
                await db.commit()
                await db.refresh(professional)

                # Publier événement de création
                await publish(
                    "identity.professional.created",
                    {
                        "professional_id": professional.id,
                        "keycloak_user_id": event.user_id,
                        "email": professional.email,
                        "client_id": event.client_id,
                        "created_at": datetime.now().isoformat(),
                    },
                )

                span.set_attribute("professional.id", professional.id)
                span.set_attribute("client.id", event.client_id or "unknown")
                logger.info(
                    f"Professional créé depuis Keycloak: professional_id={professional.id}, "
                    f"client_id={event.client_id}"
                )

                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=professional.id,  # Utilise patient_id pour compatibilité avec le schema
                    message=f"Professional created: {professional.id}",
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

            # Créer un profil Patient (par défaut)
            patient = await _create_patient_from_event(db, event)
            await db.commit()
            await db.refresh(patient)

            # Publier événement de création
            await publish(
                "identity.patient.created",
                {
                    "patient_id": patient.id,
                    "keycloak_user_id": event.user_id,
                    "email": patient.email,
                    "client_id": event.client_id,
                    "created_at": datetime.now().isoformat(),
                },
            )

            span.set_attribute("patient.id", patient.id)
            span.set_attribute("client.id", event.client_id or "unknown")
            logger.info(
                f"Patient créé depuis Keycloak: patient_id={patient.id}, client_id={event.client_id}"
            )

            return SyncResult(
                success=True,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=patient.id,
                message=f"Patient created: {patient.id}",
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
    Synchronise un événement UPDATE_PROFILE.

    Met à jour le profil Patient/Professional avec les nouvelles données.

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

            # Chercher d'abord dans Patient
            result = await db.execute(
                select(Patient).where(Patient.keycloak_user_id == event.user_id)
            )
            patient = result.scalar_one_or_none()

            # Si pas trouvé dans Patient, chercher dans Professional
            professional = None
            if not patient:
                result = await db.execute(
                    select(Professional).where(Professional.keycloak_user_id == event.user_id)
                )
                professional = result.scalar_one_or_none()

            # Si ni Patient ni Professional trouvé, retourner erreur
            if not patient and not professional:
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

            # Déterminer le profil à mettre à jour
            profile = patient if patient else professional
            profile_type = "patient" if patient else "professional"

            # Mettre à jour les champs
            updated_fields = []
            if event.user.first_name and event.user.first_name != profile.first_name:
                profile.first_name = event.user.first_name
                updated_fields.append("first_name")

            if event.user.last_name and event.user.last_name != profile.last_name:
                profile.last_name = event.user.last_name
                updated_fields.append("last_name")

            if event.user.phone and event.user.phone != profile.phone:
                profile.phone = event.user.phone
                updated_fields.append("phone")

            if updated_fields:
                profile.updated_at = datetime.now()
                await db.commit()
                await db.refresh(profile)

                # Publier événement de mise à jour selon le type
                event_subject = f"identity.{profile_type}.updated"
                await publish(
                    event_subject,
                    {
                        f"{profile_type}_id": profile.id,
                        "keycloak_user_id": event.user_id,
                        "updated_fields": updated_fields,
                        "updated_at": datetime.now().isoformat(),
                    },
                )

                logger.info(
                    f"{profile_type.capitalize()} mis à jour: {profile_type}_id={profile.id}, "
                    f"fields={updated_fields}"
                )

            span.set_attribute(f"{profile_type}.id", profile.id)
            span.set_attribute("updated_fields", str(updated_fields))

            return SyncResult(
                success=True,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=profile.id,
                message=f"Updated fields: {updated_fields}" if updated_fields else "No changes",
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
    Synchronise un événement UPDATE_EMAIL.

    Met à jour l'adresse email du Patient/Professional.

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

            # Chercher le patient
            result = await db.execute(
                select(Patient).where(Patient.keycloak_user_id == event.user_id)
            )
            patient = result.scalar_one_or_none()

            if not patient:
                logger.warning(f"Patient non trouvé pour user_id: {event.user_id}")
                return SyncResult(
                    success=False,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="Patient not found",
                )

            new_email = event.user.email
            if not new_email:
                logger.warning("Email manquant dans l'événement UPDATE_EMAIL")
                return SyncResult(
                    success=False,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=patient.id,
                    message="Email missing in event",
                )

            old_email = patient.email
            patient.email = new_email
            patient.is_verified = event.user.email_verified or False
            patient.updated_at = datetime.now()

            await db.commit()
            await db.refresh(patient)

            # Publier événement de mise à jour email
            await publish(
                "identity.patient.email_updated",
                {
                    "patient_id": patient.id,
                    "keycloak_user_id": event.user_id,
                    "old_email": old_email,
                    "new_email": new_email,
                    "email_verified": patient.is_verified,
                    "updated_at": datetime.now().isoformat(),
                },
            )

            span.set_attribute("patient.id", patient.id)
            span.set_attribute("email.old", old_email or "none")
            span.set_attribute("email.new", new_email)

            logger.info(
                f"Email mis à jour: patient_id={patient.id}, old={old_email}, new={new_email}"
            )

            return SyncResult(
                success=True,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=patient.id,
                message=f"Email updated: {old_email} -> {new_email}",
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


async def _create_patient_from_event(db: AsyncSession, event: KeycloakWebhookEvent) -> Patient:
    """
    Crée un Patient depuis un événement Keycloak.

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak

    Returns:
        Patient créé

    Raises:
        ValueError: Si données requises manquantes
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

    # Créer le patient
    patient = Patient(
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
        is_active=True,
        is_verified=user.email_verified or False,
    )

    db.add(patient)
    return patient


async def _create_professional_from_event(
    db: AsyncSession, event: KeycloakWebhookEvent
) -> Professional:
    """
    Crée un Professional depuis un événement Keycloak.

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak

    Returns:
        Professional créé

    Raises:
        ValueError: Si données requises manquantes
    """
    if not event.user:
        raise ValueError("Objet user manquant dans l'événement")

    user = event.user

    # Validation des champs requis
    if not user.first_name or not user.last_name:
        raise ValueError("first_name et last_name sont requis")

    if not user.email:
        raise ValueError("email est requis pour un professionnel")

    # Créer le professionnel avec des valeurs par défaut (à compléter par l'utilisateur)
    professional = Professional(
        keycloak_user_id=event.user_id,
        first_name=user.first_name,
        last_name=user.last_name,
        title="Dr",  # Valeur par défaut, à compléter
        specialty="Non spécifié",  # À compléter lors de l'onboarding
        professional_type="other",  # À compléter lors de l'onboarding
        email=user.email,
        phone=user.phone or "+221000000000",  # Valeur par défaut si non fourni
        phone_secondary=None,
        facility_name=None,
        qualifications=None,
        languages_spoken=user.preferred_language or "fr",
        is_active=False,  # Le profil doit être complété et validé par un admin
        is_verified=False,
        is_available=False,  # Pas disponible tant que le profil n'est pas complet
    )

    db.add(professional)
    return professional


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
) -> Professional | None:
    """
    Vérifie si un professionnel anonymisé revient en calculant son correlation_hash.

    Cette fonction permet de détecter les professionnels qui reviennent après suppression
    en comparant le hash calculé avec ceux stockés dans la base.

    Args:
        db: Session de base de données async
        email: Email du nouveau professionnel
        professional_id: Numéro d'ordre professionnel (peut être None)

    Returns:
        Professionnel anonymisé correspondant si trouvé, None sinon

    Example:
        ```python
        returning = await _check_returning_professional(db, "dr.diop@hospital.sn", "CNOM12345")
        if returning:
            logger.info(f"Professionnel revenant détecté: {returning.id}")
        ```
    """
    # Générer le hash pour ce professionnel
    correlation_hash = _generate_correlation_hash(email, professional_id)

    # Chercher professionnel avec ce hash (uniquement anonymisés)
    result = await db.execute(
        select(Professional).where(
            Professional.correlation_hash == correlation_hash,
            Professional.anonymized_at.isnot(None),  # Seulement les anonymisés
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
) -> Patient | None:
    """
    Vérifie si un patient anonymisé revient en calculant son correlation_hash.

    Cette fonction permet de détecter les patients qui reviennent après suppression
    en comparant le hash calculé avec ceux stockés dans la base.

    Args:
        db: Session de base de données async
        email: Email du nouveau patient
        national_id: Numéro d'identification nationale (peut être None)

    Returns:
        Patient anonymisé correspondant si trouvé, None sinon

    Example:
        ```python
        returning = await _check_returning_patient(db, "amadou@email.sn", "CNI123456")
        if returning:
            logger.info(f"Patient revenant détecté: {returning.id}")
        ```
    """
    # Générer le hash pour ce patient
    correlation_hash = _generate_patient_correlation_hash(email, national_id)

    # Chercher patient avec ce hash (uniquement anonymisés)
    result = await db.execute(
        select(Patient).where(
            Patient.correlation_hash == correlation_hash,
            Patient.anonymized_at.isnot(None),  # Seulement les anonymisés
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
    db: AsyncSession, event: KeycloakWebhookEvent, strategy: DeletionStrategy = "anonymize"
) -> SyncResult:
    """
    Synchronise un événement DELETE (suppression d'utilisateur Keycloak).

    Logique basée sur les rôles:
    - Si rôle "professional" → supprime dans tables professionals ET patients
    - Si rôle "patient" uniquement → supprime dans table patients uniquement

    Stratégies supportées:
    1. soft_delete: Marque comme supprimé (is_active=False, deleted_at renseigné)
    2. hard_delete: Suppression physique de la base de données (non recommandé en santé)
    3. anonymize: Anonymisation des données personnelles (RGPD compliant, recommandé)

    Args:
        db: Session de base de données async
        event: Événement webhook Keycloak
        strategy: Stratégie de suppression à utiliser

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
                # On va tenter de détecter les rôles via l'existence des profils
                has_professional_role = False
                has_patient_role = False

                # Vérifier si profil professional existe
                result_prof_check = await db.execute(
                    select(Professional).where(Professional.keycloak_user_id == event.user_id)
                )
                if result_prof_check.scalar_one_or_none():
                    has_professional_role = True
                    user_roles.append("professional")

                # Vérifier si profil patient existe
                result_patient_check = await db.execute(
                    select(Patient).where(Patient.keycloak_user_id == event.user_id)
                )
                if result_patient_check.scalar_one_or_none():
                    has_patient_role = True
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

            # Si l'utilisateur a le rôle professional, supprimer dans les deux tables
            # (car un professional est aussi un patient)
            if has_professional_role:
                # Supprimer le profil professional
                result_prof = await db.execute(
                    select(Professional).where(Professional.keycloak_user_id == event.user_id)
                )
                professional = result_prof.scalar_one_or_none()

                if professional:
                    professional_id = professional.id
                    await _apply_deletion_strategy(
                        db, professional, event, strategy, "professional"
                    )
                    deleted_tables.append("professionals")
                    logger.info(f"Professional supprimé: id={professional_id}, strategy={strategy}")

            # Supprimer le profil patient (toujours présent pour patient et professional)
            if has_patient_role or has_professional_role:
                result_patient = await db.execute(
                    select(Patient).where(Patient.keycloak_user_id == event.user_id)
                )
                patient = result_patient.scalar_one_or_none()

                if patient:
                    patient_id = patient.id
                    await _apply_deletion_strategy(db, patient, event, strategy, "patient")
                    deleted_tables.append("patients")
                    logger.info(f"Patient supprimé: id={patient_id}, strategy={strategy}")

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

            await db.commit()

            # Publier événement de suppression pour les autres services
            await publish(
                "identity.user.deleted",
                {
                    "keycloak_user_id": event.user_id,
                    "patient_id": patient_id,
                    "professional_id": professional_id,
                    "deletion_strategy": strategy,
                    "deleted_tables": deleted_tables,
                    "user_roles": user_roles,
                    "deleted_at": datetime.now().isoformat(),
                    "reason": "keycloak_account_deleted",
                },
            )

            span.set_attribute("deletion.patient_id", patient_id or "none")
            span.set_attribute("deletion.professional_id", professional_id or "none")
            span.set_attribute("deletion.tables", ",".join(deleted_tables))

            message = f"User deleted from {', '.join(deleted_tables)} using {strategy} strategy"

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
    1. Vérifie si professional sous enquête (bloque si true)
    2. Génère correlation_hash AVANT anonymisation (pour détection retours)
    3. Marque comme inactif avec soft_deleted_at
    4. Anonymisation effective après 7 jours (scheduler)

    Raises:
        ProfessionalDeletionBlockedError: Si professional.under_investigation=True
    """
    from datetime import UTC

    # CHECK: Bloquer si professionnel sous enquête
    if isinstance(entity, Professional) and entity.under_investigation:
        logger.error(
            f"Soft delete bloqué pour Professional {entity.id}: under_investigation=True",
            extra={"investigation_notes": entity.investigation_notes},
        )
        raise ProfessionalDeletionBlockedError(
            professional_id=entity.id,
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

    # STEP 1: Générer correlation_hash AVANT anonymisation (pour professionnels)
    if isinstance(entity, Professional):
        if not entity.correlation_hash:
            entity.correlation_hash = _generate_correlation_hash(
                entity.email, entity.professional_id
            )
            logger.info(
                f"Generated correlation_hash for Professional {entity.id}",
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
