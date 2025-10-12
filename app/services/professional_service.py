"""Service métier pour la gestion des professionnels de santé.

Ce module implémente la logique métier pour les opérations CRUD
et la recherche sur les professionnels.
"""

from datetime import UTC, datetime

from opentelemetry import trace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish
from app.models.professional import Professional
from app.schemas.professional import (
    ProfessionalCreate,
    ProfessionalListItem,
    ProfessionalSearchFilters,
    ProfessionalUpdate,
)

tracer = trace.get_tracer(__name__)


async def create_professional(
    db: AsyncSession,
    professional_data: ProfessionalCreate,
    current_user_id: str,
) -> Professional:
    """
    Crée un nouveau professionnel dans la base de données.

    Args:
        db: Session de base de données async
        professional_data: Données du professionnel à créer
        current_user_id: ID Keycloak de l'utilisateur créateur

    Returns:
        Professional créé avec son ID

    Raises:
        IntegrityError: Si keycloak_user_id ou professional_id existe déjà
    """
    with tracer.start_as_current_span("create_professional") as span:
        span.set_attribute("professional.keycloak_user_id", professional_data.keycloak_user_id)

        # Créer le professionnel
        professional = Professional(
            **professional_data.model_dump(),
            created_by=current_user_id,
            updated_by=current_user_id,
        )

        db.add(professional)
        await db.commit()
        await db.refresh(professional)

        span.set_attribute("professional.id", professional.id)
        span.add_event("Professionnel créé avec succès")

        # Publier événement
        await publish(
            "identity.professional.created",
            {
                "professional_id": professional.id,
                "keycloak_user_id": professional.keycloak_user_id,
                "first_name": professional.first_name,
                "last_name": professional.last_name,
                "specialty": professional.specialty,
                "professional_type": professional.professional_type,
                "created_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return professional


async def get_professional(db: AsyncSession, professional_id: int) -> Professional | None:
    """
    Récupère un professionnel par son ID.

    Args:
        db: Session de base de données async
        professional_id: ID du professionnel

    Returns:
        Professional trouvé ou None
    """
    with tracer.start_as_current_span("get_professional") as span:
        span.set_attribute("professional.id", professional_id)

        result = await db.execute(select(Professional).where(Professional.id == professional_id))
        professional = result.scalar_one_or_none()

        if professional:
            span.add_event("Professionnel trouvé")
        else:
            span.add_event("Professionnel non trouvé")

        return professional


async def get_professional_by_keycloak_id(
    db: AsyncSession, keycloak_user_id: str
) -> Professional | None:
    """
    Récupère un professionnel par son keycloak_user_id.

    Args:
        db: Session de base de données async
        keycloak_user_id: UUID Keycloak de l'utilisateur

    Returns:
        Professional trouvé ou None
    """
    with tracer.start_as_current_span("get_professional_by_keycloak_id") as span:
        span.set_attribute("professional.keycloak_user_id", keycloak_user_id)

        result = await db.execute(
            select(Professional).where(Professional.keycloak_user_id == keycloak_user_id)
        )
        professional = result.scalar_one_or_none()

        if professional:
            span.add_event("Professionnel trouvé")
            span.set_attribute("professional.id", professional.id)
        else:
            span.add_event("Professionnel non trouvé")

        return professional


async def get_professional_by_professional_id(
    db: AsyncSession, professional_id: str
) -> Professional | None:
    """
    Récupère un professionnel par son numéro d'ordre professionnel.

    Args:
        db: Session de base de données async
        professional_id: Numéro d'ordre (CNOM, etc.)

    Returns:
        Professional trouvé ou None
    """
    with tracer.start_as_current_span("get_professional_by_professional_id") as span:
        span.set_attribute("professional.professional_id", professional_id)

        result = await db.execute(
            select(Professional).where(Professional.professional_id == professional_id)
        )
        professional = result.scalar_one_or_none()

        if professional:
            span.add_event("Professionnel trouvé")
            span.set_attribute("professional.id", professional.id)

        return professional


async def update_professional(
    db: AsyncSession,
    professional_id: int,
    professional_data: ProfessionalUpdate,
    current_user_id: str,
) -> Professional | None:
    """
    Met à jour un professionnel existant.

    Args:
        db: Session de base de données async
        professional_id: ID du professionnel à mettre à jour
        professional_data: Nouvelles données du professionnel
        current_user_id: ID Keycloak de l'utilisateur modificateur

    Returns:
        Professional mis à jour ou None si non trouvé
    """
    with tracer.start_as_current_span("update_professional") as span:
        span.set_attribute("professional.id", professional_id)

        professional = await get_professional(db, professional_id)
        if not professional:
            span.add_event("Professionnel non trouvé")
            return None

        # Mettre à jour uniquement les champs fournis
        update_data = professional_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(professional, field, value)

        professional.updated_by = current_user_id
        professional.updated_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(professional)

        span.add_event("Professionnel mis à jour avec succès")

        # Publier événement
        await publish(
            "identity.professional.updated",
            {
                "professional_id": professional.id,
                "keycloak_user_id": professional.keycloak_user_id,
                "updated_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return professional


async def delete_professional(
    db: AsyncSession,
    professional_id: int,
    current_user_id: str,
) -> bool:
    """
    Supprime (soft delete) un professionnel en le marquant comme inactif.

    Args:
        db: Session de base de données async
        professional_id: ID du professionnel à supprimer
        current_user_id: ID Keycloak de l'utilisateur

    Returns:
        True si supprimé, False si non trouvé
    """
    with tracer.start_as_current_span("delete_professional") as span:
        span.set_attribute("professional.id", professional_id)

        professional = await get_professional(db, professional_id)
        if not professional:
            span.add_event("Professionnel non trouvé")
            return False

        # Soft delete : marquer comme inactif
        professional.is_active = False
        professional.updated_by = current_user_id
        professional.updated_at = datetime.now(UTC)

        await db.commit()

        span.add_event("Professionnel désactivé (soft delete)")

        # Publier événement
        await publish(
            "identity.professional.deactivated",
            {
                "professional_id": professional.id,
                "keycloak_user_id": professional.keycloak_user_id,
                "deactivated_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return True


async def search_professionals(  # noqa: C901
    db: AsyncSession,
    filters: ProfessionalSearchFilters,
) -> tuple[list[ProfessionalListItem], int]:
    """
    Recherche des professionnels selon des critères de filtrage.

    Args:
        db: Session de base de données async
        filters: Critères de recherche et pagination

    Returns:
        Tuple (liste des professionnels, nombre total de résultats)
    """
    with tracer.start_as_current_span("search_professionals") as span:
        # Construction de la requête de base
        query = select(Professional)

        # Application des filtres
        if filters.first_name:
            query = query.where(Professional.first_name.ilike(f"%{filters.first_name}%"))
        if filters.last_name:
            query = query.where(Professional.last_name.ilike(f"%{filters.last_name}%"))
        if filters.professional_id:
            query = query.where(Professional.professional_id == filters.professional_id)
        if filters.specialty:
            query = query.where(Professional.specialty.ilike(f"%{filters.specialty}%"))
        if filters.professional_type:
            query = query.where(Professional.professional_type == filters.professional_type)
        if filters.facility_name:
            query = query.where(Professional.facility_name.ilike(f"%{filters.facility_name}%"))
        if filters.facility_city:
            query = query.where(Professional.facility_city == filters.facility_city)
        if filters.facility_region:
            query = query.where(Professional.facility_region == filters.facility_region)
        if filters.is_active is not None:
            query = query.where(Professional.is_active == filters.is_active)
        if filters.is_verified is not None:
            query = query.where(Professional.is_verified == filters.is_verified)
        if filters.is_available is not None:
            query = query.where(Professional.is_available == filters.is_available)

        # Compter le total
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar_one()

        span.set_attribute("search.total_results", total)

        # Pagination et tri
        query = query.order_by(Professional.created_at.desc())
        query = query.offset(filters.skip).limit(filters.limit)

        # Exécuter la requête
        result = await db.execute(query)
        professionals = result.scalars().all()

        span.set_attribute("search.returned_results", len(professionals))
        span.add_event("Recherche terminée")

        # Convertir en ProfessionalListItem
        professional_items = [ProfessionalListItem.model_validate(prof) for prof in professionals]

        return professional_items, total


async def verify_professional(
    db: AsyncSession,
    professional_id: int,
    current_user_id: str,
) -> Professional | None:
    """
    Marque un professionnel comme vérifié.

    Args:
        db: Session de base de données async
        professional_id: ID du professionnel
        current_user_id: ID Keycloak de l'admin vérifiant

    Returns:
        Professional vérifié ou None si non trouvé
    """
    with tracer.start_as_current_span("verify_professional") as span:
        span.set_attribute("professional.id", professional_id)

        professional = await get_professional(db, professional_id)
        if not professional:
            return None

        professional.is_verified = True
        professional.updated_by = current_user_id
        professional.updated_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(professional)

        span.add_event("Professionnel vérifié")

        # Publier événement
        await publish(
            "identity.professional.verified",
            {
                "professional_id": professional.id,
                "keycloak_user_id": professional.keycloak_user_id,
                "verified_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return professional


async def toggle_availability(
    db: AsyncSession,
    professional_id: int,
    is_available: bool,
    current_user_id: str,
) -> Professional | None:
    """
    Change la disponibilité d'un professionnel pour consultations.

    Args:
        db: Session de base de données async
        professional_id: ID du professionnel
        is_available: True pour disponible, False pour indisponible
        current_user_id: ID Keycloak

    Returns:
        Professional mis à jour ou None si non trouvé
    """
    with tracer.start_as_current_span("toggle_availability") as span:
        span.set_attribute("professional.id", professional_id)
        span.set_attribute("professional.is_available", is_available)

        professional = await get_professional(db, professional_id)
        if not professional:
            return None

        professional.is_available = is_available
        professional.updated_by = current_user_id
        professional.updated_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(professional)

        span.add_event("Disponibilité mise à jour")

        # Publier événement
        await publish(
            "identity.professional.availability_changed",
            {
                "professional_id": professional.id,
                "keycloak_user_id": professional.keycloak_user_id,
                "is_available": is_available,
                "changed_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return professional
