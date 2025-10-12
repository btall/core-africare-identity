"""Service métier pour la gestion des patients.

Ce module implémente la logique métier pour les opérations CRUD
et la recherche sur les patients.
"""

from datetime import UTC, datetime

from opentelemetry import trace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish
from app.models.patient import Patient
from app.schemas.patient import (
    PatientCreate,
    PatientListItem,
    PatientSearchFilters,
    PatientUpdate,
)

tracer = trace.get_tracer(__name__)


async def create_patient(
    db: AsyncSession,
    patient_data: PatientCreate,
    current_user_id: str,
) -> Patient:
    """
    Crée un nouveau patient dans la base de données.

    Args:
        db: Session de base de données async
        patient_data: Données du patient à créer
        current_user_id: ID Keycloak de l'utilisateur créateur

    Returns:
        Patient créé avec son ID

    Raises:
        IntegrityError: Si keycloak_user_id ou national_id existe déjà
    """
    with tracer.start_as_current_span("create_patient") as span:
        span.set_attribute("patient.keycloak_user_id", patient_data.keycloak_user_id)

        # Créer le patient
        patient = Patient(
            **patient_data.model_dump(),
            created_by=current_user_id,
            updated_by=current_user_id,
        )

        db.add(patient)
        await db.commit()
        await db.refresh(patient)

        span.set_attribute("patient.id", patient.id)
        span.add_event("Patient créé avec succès")

        # Publier événement
        await publish(
            "identity.patient.created",
            {
                "patient_id": patient.id,
                "keycloak_user_id": patient.keycloak_user_id,
                "first_name": patient.first_name,
                "last_name": patient.last_name,
                "created_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return patient


async def get_patient(db: AsyncSession, patient_id: int) -> Patient | None:
    """
    Récupère un patient par son ID.

    Args:
        db: Session de base de données async
        patient_id: ID du patient

    Returns:
        Patient trouvé ou None
    """
    with tracer.start_as_current_span("get_patient") as span:
        span.set_attribute("patient.id", patient_id)

        result = await db.execute(select(Patient).where(Patient.id == patient_id))
        patient = result.scalar_one_or_none()

        if patient:
            span.add_event("Patient trouvé")
        else:
            span.add_event("Patient non trouvé")

        return patient


async def get_patient_by_keycloak_id(db: AsyncSession, keycloak_user_id: str) -> Patient | None:
    """
    Récupère un patient par son keycloak_user_id.

    Args:
        db: Session de base de données async
        keycloak_user_id: UUID Keycloak de l'utilisateur

    Returns:
        Patient trouvé ou None
    """
    with tracer.start_as_current_span("get_patient_by_keycloak_id") as span:
        span.set_attribute("patient.keycloak_user_id", keycloak_user_id)

        result = await db.execute(
            select(Patient).where(Patient.keycloak_user_id == keycloak_user_id)
        )
        patient = result.scalar_one_or_none()

        if patient:
            span.add_event("Patient trouvé")
            span.set_attribute("patient.id", patient.id)
        else:
            span.add_event("Patient non trouvé")

        return patient


async def get_patient_by_national_id(db: AsyncSession, national_id: str) -> Patient | None:
    """
    Récupère un patient par son identifiant national.

    Args:
        db: Session de base de données async
        national_id: Identifiant national (CNI, passeport, etc.)

    Returns:
        Patient trouvé ou None
    """
    with tracer.start_as_current_span("get_patient_by_national_id") as span:
        span.set_attribute("patient.national_id", national_id)

        result = await db.execute(select(Patient).where(Patient.national_id == national_id))
        patient = result.scalar_one_or_none()

        if patient:
            span.add_event("Patient trouvé")
            span.set_attribute("patient.id", patient.id)

        return patient


async def update_patient(
    db: AsyncSession,
    patient_id: int,
    patient_data: PatientUpdate,
    current_user_id: str,
) -> Patient | None:
    """
    Met à jour un patient existant.

    Args:
        db: Session de base de données async
        patient_id: ID du patient à mettre à jour
        patient_data: Nouvelles données du patient
        current_user_id: ID Keycloak de l'utilisateur modificateur

    Returns:
        Patient mis à jour ou None si non trouvé
    """
    with tracer.start_as_current_span("update_patient") as span:
        span.set_attribute("patient.id", patient_id)

        patient = await get_patient(db, patient_id)
        if not patient:
            span.add_event("Patient non trouvé")
            return None

        # Mettre à jour uniquement les champs fournis
        update_data = patient_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(patient, field, value)

        patient.updated_by = current_user_id
        patient.updated_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(patient)

        span.add_event("Patient mis à jour avec succès")

        # Publier événement
        await publish(
            "identity.patient.updated",
            {
                "patient_id": patient.id,
                "keycloak_user_id": patient.keycloak_user_id,
                "updated_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return patient


async def delete_patient(
    db: AsyncSession,
    patient_id: int,
    current_user_id: str,
) -> bool:
    """
    Supprime (soft delete) un patient en le marquant comme inactif.

    Args:
        db: Session de base de données async
        patient_id: ID du patient à supprimer
        current_user_id: ID Keycloak de l'utilisateur

    Returns:
        True si supprimé, False si non trouvé
    """
    with tracer.start_as_current_span("delete_patient") as span:
        span.set_attribute("patient.id", patient_id)

        patient = await get_patient(db, patient_id)
        if not patient:
            span.add_event("Patient non trouvé")
            return False

        # Soft delete : marquer comme inactif
        patient.is_active = False
        patient.updated_by = current_user_id
        patient.updated_at = datetime.now(UTC)

        await db.commit()

        span.add_event("Patient désactivé (soft delete)")

        # Publier événement
        await publish(
            "identity.patient.deactivated",
            {
                "patient_id": patient.id,
                "keycloak_user_id": patient.keycloak_user_id,
                "deactivated_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return True


async def search_patients(  # noqa: C901
    db: AsyncSession,
    filters: PatientSearchFilters,
) -> tuple[list[PatientListItem], int]:
    """
    Recherche des patients selon des critères de filtrage.

    Args:
        db: Session de base de données async
        filters: Critères de recherche et pagination

    Returns:
        Tuple (liste des patients, nombre total de résultats)
    """
    with tracer.start_as_current_span("search_patients") as span:
        # Construction de la requête de base
        query = select(Patient)

        # Application des filtres
        if filters.first_name:
            query = query.where(Patient.first_name.ilike(f"%{filters.first_name}%"))
        if filters.last_name:
            query = query.where(Patient.last_name.ilike(f"%{filters.last_name}%"))
        if filters.national_id:
            query = query.where(Patient.national_id == filters.national_id)
        if filters.email:
            query = query.where(Patient.email == filters.email)
        if filters.phone:
            query = query.where(Patient.phone == filters.phone)
        if filters.gender:
            query = query.where(Patient.gender == filters.gender)
        if filters.is_active is not None:
            query = query.where(Patient.is_active == filters.is_active)
        if filters.is_verified is not None:
            query = query.where(Patient.is_verified == filters.is_verified)
        if filters.region:
            query = query.where(Patient.region == filters.region)
        if filters.city:
            query = query.where(Patient.city == filters.city)

        # Compter le total
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar_one()

        span.set_attribute("search.total_results", total)

        # Pagination et tri
        query = query.order_by(Patient.created_at.desc())
        query = query.offset(filters.skip).limit(filters.limit)

        # Exécuter la requête
        result = await db.execute(query)
        patients = result.scalars().all()

        span.set_attribute("search.returned_results", len(patients))
        span.add_event("Recherche terminée")

        # Convertir en PatientListItem
        patient_items = [PatientListItem.model_validate(patient) for patient in patients]

        return patient_items, total


async def verify_patient(
    db: AsyncSession,
    patient_id: int,
    current_user_id: str,
) -> Patient | None:
    """
    Marque un patient comme vérifié.

    Args:
        db: Session de base de données async
        patient_id: ID du patient
        current_user_id: ID Keycloak du professionnel vérifiant

    Returns:
        Patient vérifié ou None si non trouvé
    """
    with tracer.start_as_current_span("verify_patient") as span:
        span.set_attribute("patient.id", patient_id)

        patient = await get_patient(db, patient_id)
        if not patient:
            return None

        patient.is_verified = True
        patient.updated_by = current_user_id
        patient.updated_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(patient)

        span.add_event("Patient vérifié")

        # Publier événement
        await publish(
            "identity.patient.verified",
            {
                "patient_id": patient.id,
                "keycloak_user_id": patient.keycloak_user_id,
                "verified_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return patient
