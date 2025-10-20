"""Service de synchronisation des événements Keycloak vers PostgreSQL.

Ce module implémente la logique de synchronisation temps-réel
entre les événements Keycloak et la base de données locale.
"""

import logging
from datetime import datetime
from typing import Literal

from keycloak import KeycloakAdmin
from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.events import publish
from app.core.retry import async_retry_with_backoff
from app.models.patient import Patient
from app.models.professional import Professional
from app.schemas.keycloak import KeycloakWebhookEvent, SyncResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Client admin Keycloak pour récupérer les rôles utilisateur
keycloak_admin = KeycloakAdmin(
    server_url=settings.KEYCLOAK_SERVER_URL,
    realm_name=settings.KEYCLOAK_REALM,
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

    Note:
        En cas d'erreur lors de la récupération des rôles, retourne une liste vide
        et log l'erreur pour investigation.
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
            # Retourner liste vide en cas d'erreur
            return []


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

            # Vérifier si l'utilisateur existe déjà
            existing_patient = await db.execute(
                select(Patient).where(Patient.keycloak_user_id == event.user_id)
            )
            if existing_patient.scalar_one_or_none():
                logger.info(f"Utilisateur déjà synchronisé: {event.user_id}")
                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="User already synchronized",
                )

            # Déterminer le type de profil (patient par défaut)
            # TODO: Ajouter logique pour distinguer professional vs patient
            user_role = "patient"  # Temporaire

            if user_role == "patient":
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
                        "created_at": datetime.now().isoformat(),
                    },
                )

                span.set_attribute("patient.id", patient.id)
                logger.info(f"Patient créé depuis Keycloak: patient_id={patient.id}")

                return SyncResult(
                    success=True,
                    event_type=event.event_type,
                    user_id=event.user_id,
                    patient_id=patient.id,
                    message=f"Patient created: {patient.id}",
                )

            # TODO: Implémenter création professional
            return SyncResult(
                success=False,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=None,
                message="Professional sync not implemented",
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

            # Mettre à jour les champs
            updated_fields = []
            if event.user.first_name and event.user.first_name != patient.first_name:
                patient.first_name = event.user.first_name
                updated_fields.append("first_name")

            if event.user.last_name and event.user.last_name != patient.last_name:
                patient.last_name = event.user.last_name
                updated_fields.append("last_name")

            if event.user.phone and event.user.phone != patient.phone:
                patient.phone = event.user.phone
                updated_fields.append("phone")

            if updated_fields:
                patient.updated_at = datetime.now()
                await db.commit()
                await db.refresh(patient)

                # Publier événement de mise à jour
                await publish(
                    "identity.patient.updated",
                    {
                        "patient_id": patient.id,
                        "keycloak_user_id": event.user_id,
                        "updated_fields": updated_fields,
                        "updated_at": datetime.now().isoformat(),
                    },
                )

                logger.info(f"Patient mis à jour: patient_id={patient.id}, fields={updated_fields}")

            span.set_attribute("patient.id", patient.id)
            span.set_attribute("updated_fields", str(updated_fields))

            return SyncResult(
                success=True,
                event_type=event.event_type,
                user_id=event.user_id,
                patient_id=patient.id,
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


################################################################################
# Fonctions de suppression d'utilisateur (DELETE event)
################################################################################


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
            user_roles = await get_user_roles_from_keycloak(event.user_id)
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
    Soft delete: Marque l'entité comme supprimée sans effacer les données.

    - is_active = False
    - deleted_at = maintenant
    - deleted_by = user_id (auto-suppression)
    - deletion_reason = user_request
    """
    entity.is_active = False
    entity.deleted_at = datetime.now()
    entity.deleted_by = event.user_id
    entity.deletion_reason = "user_request"
    entity.updated_at = datetime.now()

    logger.info(f"Soft delete {entity.__class__.__name__}: {entity.id}")


async def _anonymize(
    entity: Patient | Professional,
    event: KeycloakWebhookEvent,
    entity_type: Literal["patient", "professional"],
) -> None:
    """
    Anonymisation: Remplace les données personnelles par des valeurs anonymes.

    Préserve:
    - ID (pour relations avec autres services)
    - Date de naissance / années d'expérience (pour statistiques)
    - Genre / spécialité (pour statistiques médicales)
    - Dates de création/modification (audit)

    Anonymise:
    - Prénom/Nom
    - Email
    - Téléphone
    - Adresse
    - GPS (pour patients)
    - Contact d'urgence
    - Identifiants nationaux
    """
    entity_id = entity.id

    # Anonymiser les données communes
    entity.first_name = f"ANONYME_{entity_id}"
    entity.last_name = f"{entity_type.upper()}_{entity_id}"
    entity.email = f"deleted_{entity_id}@anonymized.local"
    entity.phone = None

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


async def _hard_delete(db: AsyncSession, entity: Patient | Professional) -> None:
    """
    Hard delete: Suppression physique de l'entité.

    ATTENTION: Cette méthode supprime définitivement toutes les données.
    À utiliser uniquement dans des contextes non-médicaux ou après anonymisation
    des données médicales dans les autres services.
    """
    entity_id = entity.id
    entity_type = entity.__class__.__name__

    await db.delete(entity)
    logger.warning(f"Hard delete {entity_type}: {entity_id}")
