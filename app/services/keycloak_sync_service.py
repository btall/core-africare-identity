"""Service de synchronisation des événements Keycloak vers PostgreSQL.

Ce module implémente la logique de synchronisation temps-réel
entre les événements Keycloak et la base de données locale.
"""

import logging
from datetime import date, datetime

from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish
from app.models.patient import Patient
from app.schemas.keycloak import KeycloakWebhookEvent, SyncResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


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
        span.set_attribute("event.type", event.type)
        span.set_attribute("event.user_id", event.user_id)

        try:
            # Vérifier si l'utilisateur existe déjà
            existing_patient = await db.execute(
                select(Patient).where(Patient.keycloak_user_id == event.user_id)
            )
            if existing_patient.scalar_one_or_none():
                logger.info(f"Utilisateur déjà synchronisé: {event.user_id}")
                return SyncResult(
                    success=True,
                    event_type=event.type,
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
                    event_type=event.type,
                    user_id=event.user_id,
                    patient_id=patient.id,
                    message=f"Patient created: {patient.id}",
                )

            # TODO: Implémenter création professional
            return SyncResult(
                success=False,
                event_type=event.type,
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
        span.set_attribute("event.type", event.type)
        span.set_attribute("event.user_id", event.user_id)

        try:
            # Chercher le patient
            result = await db.execute(
                select(Patient).where(Patient.keycloak_user_id == event.user_id)
            )
            patient = result.scalar_one_or_none()

            if not patient:
                logger.warning(f"Patient non trouvé pour user_id: {event.user_id}")
                return SyncResult(
                    success=False,
                    event_type=event.type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="Patient not found",
                )

            # Mettre à jour les champs
            updated_fields = []
            if event.details.first_name and event.details.first_name != patient.first_name:
                patient.first_name = event.details.first_name
                updated_fields.append("first_name")

            if event.details.last_name and event.details.last_name != patient.last_name:
                patient.last_name = event.details.last_name
                updated_fields.append("last_name")

            if event.details.phone and event.details.phone != patient.phone:
                patient.phone = event.details.phone
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
                event_type=event.type,
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
        span.set_attribute("event.type", event.type)
        span.set_attribute("event.user_id", event.user_id)

        try:
            # Chercher le patient
            result = await db.execute(
                select(Patient).where(Patient.keycloak_user_id == event.user_id)
            )
            patient = result.scalar_one_or_none()

            if not patient:
                logger.warning(f"Patient non trouvé pour user_id: {event.user_id}")
                return SyncResult(
                    success=False,
                    event_type=event.type,
                    user_id=event.user_id,
                    patient_id=None,
                    message="Patient not found",
                )

            new_email = event.details.email
            if not new_email:
                logger.warning("Email manquant dans l'événement UPDATE_EMAIL")
                return SyncResult(
                    success=False,
                    event_type=event.type,
                    user_id=event.user_id,
                    patient_id=patient.id,
                    message="Email missing in event",
                )

            old_email = patient.email
            patient.email = new_email
            patient.is_verified = event.details.email_verified or False
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
                event_type=event.type,
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
        span.set_attribute("event.type", event.type)
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
                event_type=event.type,
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
    details = event.details

    # Validation des champs requis
    if not details.first_name or not details.last_name:
        raise ValueError("first_name et last_name sont requis")

    if not details.date_of_birth:
        raise ValueError("date_of_birth est requis")

    if not details.gender:
        raise ValueError("gender est requis")

    # Parser la date de naissance
    try:
        dob = date.fromisoformat(details.date_of_birth)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Format date_of_birth invalide: {details.date_of_birth}") from e

    # Créer le patient
    patient = Patient(
        keycloak_user_id=event.user_id,
        first_name=details.first_name,
        last_name=details.last_name,
        date_of_birth=dob,
        gender=details.gender,
        email=details.email,
        phone=details.phone,
        national_id=details.national_id,
        country=details.country or "Sénégal",
        region=details.region,
        city=details.city,
        preferred_language=details.preferred_language or "fr",
        is_active=True,
        is_verified=details.email_verified or False,
    )

    db.add(patient)
    return patient
