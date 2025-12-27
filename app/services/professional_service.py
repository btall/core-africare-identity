"""Service metier pour la gestion des professionnels de sante.

Ce module implemente la logique metier pour les operations CRUD
sur les professionnels avec architecture hybride:
- HAPI FHIR: Source de verite pour donnees demographiques (Practitioner)
- PostgreSQL: Metadonnees GDPR locales
"""

from datetime import UTC, datetime

from fhir.resources.practitioner import Practitioner as FHIRPractitioner
from opentelemetry import trace
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish
from app.infrastructure.fhir.client import get_fhir_client
from app.infrastructure.fhir.exceptions import FHIRResourceNotFoundError
from app.infrastructure.fhir.identifiers import KEYCLOAK_SYSTEM, PROFESSIONAL_LICENSE_SYSTEM
from app.infrastructure.fhir.mappers.professional_mapper import ProfessionalMapper
from app.models.gdpr_metadata import ProfessionalGdprMetadata
from app.schemas.professional import (
    ProfessionalCreate,
    ProfessionalListItem,
    ProfessionalResponse,
    ProfessionalSearchFilters,
    ProfessionalUpdate,
)

tracer = trace.get_tracer(__name__)


async def create_professional(
    db: AsyncSession,
    professional_data: ProfessionalCreate,
    current_user_id: str,
) -> ProfessionalResponse:
    """
    Cree un nouveau professionnel dans FHIR et les metadonnees locales.

    Pattern d'orchestration:
    1. Mapper vers FHIR Practitioner
    2. Creer dans HAPI FHIR
    3. Creer metadonnees GDPR locales
    4. Publier evenement
    5. Retourner response avec ID numerique

    Args:
        db: Session de base de donnees async
        professional_data: Donnees du professionnel a creer
        current_user_id: ID Keycloak de l'utilisateur createur

    Returns:
        ProfessionalResponse avec ID numerique local

    Raises:
        FHIROperationError: Si creation FHIR echoue
        IntegrityError: Si keycloak_user_id existe deja
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("create_professional") as span:
        span.set_attribute("professional.keycloak_user_id", professional_data.keycloak_user_id)

        # 1. Mapper vers FHIR Practitioner
        fhir_practitioner = ProfessionalMapper.to_fhir(professional_data)

        # 2. Creer dans HAPI FHIR
        created_fhir: FHIRPractitioner = await fhir_client.create(fhir_practitioner)
        span.set_attribute("fhir.resource_id", created_fhir.id)

        # 3. Creer metadonnees GDPR locales
        gdpr_metadata = ProfessionalGdprMetadata(
            fhir_resource_id=created_fhir.id,
            keycloak_user_id=professional_data.keycloak_user_id,
            is_verified=False,
            is_available=professional_data.is_available,
            notes=professional_data.notes,
            created_by=current_user_id,
            updated_by=current_user_id,
        )
        db.add(gdpr_metadata)
        await db.commit()
        await db.refresh(gdpr_metadata)

        span.set_attribute("professional.id", gdpr_metadata.id)
        span.add_event("Professionnel cree avec succes")

        # 4. Publier evenement
        await publish(
            "identity.professional.created",
            {
                "professional_id": gdpr_metadata.id,
                "fhir_resource_id": created_fhir.id,
                "keycloak_user_id": professional_data.keycloak_user_id,
                "first_name": professional_data.first_name,
                "last_name": professional_data.last_name,
                "specialty": professional_data.specialty,
                "professional_type": professional_data.professional_type,
                "created_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # 5. Retourner response avec ID numerique
        return ProfessionalMapper.from_fhir(
            created_fhir,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )


async def get_professional(
    db: AsyncSession,
    professional_id: int,
) -> ProfessionalResponse | None:
    """
    Recupere un professionnel par son ID numerique local.

    Pattern:
    1. Lookup local pour obtenir fhir_resource_id
    2. Fetch depuis HAPI FHIR
    3. Combiner avec metadonnees GDPR

    Args:
        db: Session de base de donnees async
        professional_id: ID numerique du professionnel

    Returns:
        ProfessionalResponse ou None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("get_professional") as span:
        span.set_attribute("professional.id", professional_id)

        # 1. Lookup local
        result = await db.execute(
            select(ProfessionalGdprMetadata).where(
                ProfessionalGdprMetadata.id == professional_id,
                ProfessionalGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            span.add_event("Professionnel non trouve (local)")
            return None

        # 2. Fetch depuis HAPI FHIR
        fhir_practitioner = await fhir_client.read("Practitioner", gdpr_metadata.fhir_resource_id)
        if not fhir_practitioner:
            span.add_event("Professionnel non trouve (FHIR)")
            return None

        span.add_event("Professionnel trouve")

        # 3. Combiner avec metadonnees GDPR
        return ProfessionalMapper.from_fhir(
            fhir_practitioner,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )


async def get_professional_by_keycloak_id(
    db: AsyncSession,
    keycloak_user_id: str,
) -> ProfessionalResponse | None:
    """
    Recupere un professionnel par son keycloak_user_id.

    Args:
        db: Session de base de donnees async
        keycloak_user_id: UUID Keycloak de l'utilisateur

    Returns:
        ProfessionalResponse ou None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("get_professional_by_keycloak_id") as span:
        span.set_attribute("professional.keycloak_user_id", keycloak_user_id)

        # Lookup local par keycloak_user_id
        result = await db.execute(
            select(ProfessionalGdprMetadata).where(
                ProfessionalGdprMetadata.keycloak_user_id == keycloak_user_id,
                ProfessionalGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            span.add_event("Professionnel non trouve")
            return None

        # Fetch depuis FHIR
        fhir_practitioner = await fhir_client.read("Practitioner", gdpr_metadata.fhir_resource_id)
        if not fhir_practitioner:
            return None

        span.set_attribute("professional.id", gdpr_metadata.id)
        span.add_event("Professionnel trouve")

        return ProfessionalMapper.from_fhir(
            fhir_practitioner,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )


async def get_professional_by_professional_id(
    db: AsyncSession,
    professional_id: str,
) -> ProfessionalResponse | None:
    """
    Recupere un professionnel par son numero d'ordre via FHIR search.

    Args:
        db: Session de base de donnees async
        professional_id: Numero d'ordre (CNOM, etc.)

    Returns:
        ProfessionalResponse ou None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("get_professional_by_professional_id") as span:
        span.set_attribute("professional.professional_id", professional_id)

        # Recherche FHIR par identifier
        fhir_practitioner = await fhir_client.search_by_identifier(
            "Practitioner", PROFESSIONAL_LICENSE_SYSTEM, professional_id
        )

        if not fhir_practitioner:
            span.add_event("Professionnel non trouve (FHIR)")
            return None

        # Lookup local pour obtenir ID et metadonnees
        keycloak_id = _extract_keycloak_id(fhir_practitioner)
        if not keycloak_id:
            return None

        result = await db.execute(
            select(ProfessionalGdprMetadata).where(
                ProfessionalGdprMetadata.keycloak_user_id == keycloak_id,
                ProfessionalGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            return None

        span.set_attribute("professional.id", gdpr_metadata.id)
        span.add_event("Professionnel trouve")

        return ProfessionalMapper.from_fhir(
            fhir_practitioner,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )


async def update_professional(
    db: AsyncSession,
    professional_id: int,
    professional_data: ProfessionalUpdate,
    current_user_id: str,
) -> ProfessionalResponse | None:
    """
    Met a jour un professionnel existant.

    Pattern:
    1. Lookup local
    2. Fetch FHIR Practitioner
    3. Appliquer updates via mapper
    4. Update dans FHIR
    5. Update metadonnees locales si necessaire
    6. Publier evenement

    Args:
        db: Session de base de donnees async
        professional_id: ID du professionnel a mettre a jour
        professional_data: Nouvelles donnees du professionnel
        current_user_id: ID Keycloak de l'utilisateur modificateur

    Returns:
        ProfessionalResponse mis a jour ou None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("update_professional") as span:
        span.set_attribute("professional.id", professional_id)

        # 1. Lookup local
        result = await db.execute(
            select(ProfessionalGdprMetadata).where(
                ProfessionalGdprMetadata.id == professional_id,
                ProfessionalGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            span.add_event("Professionnel non trouve")
            return None

        # 2. Fetch FHIR Practitioner
        fhir_practitioner = await fhir_client.read("Practitioner", gdpr_metadata.fhir_resource_id)
        if not fhir_practitioner:
            return None

        # 3. Appliquer updates via mapper
        updated_fhir = ProfessionalMapper.apply_updates(fhir_practitioner, professional_data)

        # 4. Update dans FHIR
        try:
            updated_fhir = await fhir_client.update(updated_fhir)
        except FHIRResourceNotFoundError:
            return None

        # 5. Update metadonnees locales si necessaire
        if professional_data.is_available is not None:
            gdpr_metadata.is_available = professional_data.is_available
        if professional_data.notes is not None:
            gdpr_metadata.notes = professional_data.notes
        gdpr_metadata.updated_by = current_user_id
        gdpr_metadata.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(gdpr_metadata)

        span.add_event("Professionnel mis a jour avec succes")

        # 6. Publier evenement
        await publish(
            "identity.professional.updated",
            {
                "professional_id": gdpr_metadata.id,
                "fhir_resource_id": gdpr_metadata.fhir_resource_id,
                "keycloak_user_id": gdpr_metadata.keycloak_user_id,
                "updated_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return ProfessionalMapper.from_fhir(
            updated_fhir,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )


async def delete_professional(
    db: AsyncSession,
    professional_id: int,
    current_user_id: str,
    deletion_reason: str = "user_request",
) -> bool:
    """
    Soft delete un professionnel (RGPD compliant).

    Pattern:
    1. Marquer metadonnees locales comme supprimees
    2. Desactiver ressource FHIR (active=false)
    3. Publier evenement

    Note: L'anonymisation definitive se fait apres periode de grace (7 jours).

    Args:
        db: Session de base de donnees async
        professional_id: ID du professionnel a supprimer
        current_user_id: ID Keycloak de l'utilisateur
        deletion_reason: Raison de la suppression

    Returns:
        True si supprime, False si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("delete_professional") as span:
        span.set_attribute("professional.id", professional_id)

        # Lookup local
        result = await db.execute(
            select(ProfessionalGdprMetadata).where(
                ProfessionalGdprMetadata.id == professional_id,
                ProfessionalGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            span.add_event("Professionnel non trouve")
            return False

        # Verifier si sous enquete
        if gdpr_metadata.under_investigation:
            span.add_event("Professionnel sous enquete - suppression bloquee")
            return False

        # 1. Marquer localement comme supprime
        gdpr_metadata.soft_deleted_at = datetime.now(UTC)
        gdpr_metadata.deleted_by = current_user_id
        gdpr_metadata.deletion_reason = deletion_reason
        gdpr_metadata.updated_by = current_user_id
        gdpr_metadata.updated_at = datetime.now(UTC)

        # 2. Desactiver dans FHIR
        fhir_practitioner = await fhir_client.read("Practitioner", gdpr_metadata.fhir_resource_id)
        if fhir_practitioner:
            fhir_practitioner.active = False
            await fhir_client.update(fhir_practitioner)

        await db.commit()

        span.add_event("Professionnel desactive (soft delete)")

        # 3. Publier evenement
        await publish(
            "identity.professional.deactivated",
            {
                "professional_id": gdpr_metadata.id,
                "fhir_resource_id": gdpr_metadata.fhir_resource_id,
                "keycloak_user_id": gdpr_metadata.keycloak_user_id,
                "deactivated_by": current_user_id,
                "deletion_reason": deletion_reason,
                "grace_period_ends": (
                    gdpr_metadata.soft_deleted_at.isoformat()
                    if gdpr_metadata.soft_deleted_at
                    else None
                ),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return True


async def search_professionals(
    db: AsyncSession,
    filters: ProfessionalSearchFilters,
) -> tuple[list[ProfessionalListItem], int]:
    """
    Recherche des professionnels selon des criteres de filtrage.

    Strategie hybride:
    - Filtres demographiques: FHIR search
    - Filtres GDPR (is_verified, is_available): Local join

    Args:
        db: Session de base de donnees async
        filters: Criteres de recherche et pagination

    Returns:
        Tuple (liste des professionnels, nombre total de resultats)
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("search_professionals") as span:
        # Construire params FHIR
        fhir_params = _build_fhir_search_params(filters)

        # Recherche FHIR
        bundle = await fhir_client.search("Practitioner", params=fhir_params)
        total_fhir = bundle.total or 0

        if not bundle.entry:
            span.set_attribute("search.total_results", 0)
            return [], 0

        # Extraire keycloak_ids pour lookup local
        fhir_practitioners = {}
        keycloak_ids = []
        for entry in bundle.entry:
            if entry.resource:
                practitioner = entry.resource
                keycloak_id = _extract_keycloak_id(practitioner)
                if keycloak_id:
                    fhir_practitioners[keycloak_id] = practitioner
                    keycloak_ids.append(keycloak_id)

        # Lookup local pour metadonnees et IDs
        local_query = select(ProfessionalGdprMetadata).where(
            ProfessionalGdprMetadata.keycloak_user_id.in_(keycloak_ids),
            ProfessionalGdprMetadata.soft_deleted_at.is_(None),
        )

        # Appliquer filtres locaux
        if filters.is_verified is not None:
            local_query = local_query.where(
                ProfessionalGdprMetadata.is_verified == filters.is_verified
            )
        if filters.is_available is not None:
            local_query = local_query.where(
                ProfessionalGdprMetadata.is_available == filters.is_available
            )

        local_result = await db.execute(local_query)
        gdpr_records = {r.keycloak_user_id: r for r in local_result.scalars().all()}

        # Combiner resultats
        professional_items = []
        for keycloak_id, fhir_practitioner in fhir_practitioners.items():
            gdpr = gdpr_records.get(keycloak_id)
            if gdpr:
                item = ProfessionalMapper.to_list_item(
                    fhir_practitioner,
                    local_id=gdpr.id,
                    gdpr_metadata=gdpr.to_dict(),
                )
                professional_items.append(item)

        # Compter total avec filtres locaux
        total = (
            len(professional_items)
            if filters.is_verified is not None or filters.is_available is not None
            else total_fhir
        )

        span.set_attribute("search.total_results", total)
        span.set_attribute("search.returned_results", len(professional_items))
        span.add_event("Recherche terminee")

        return professional_items, total


async def verify_professional(
    db: AsyncSession,
    professional_id: int,
    current_user_id: str,
) -> ProfessionalResponse | None:
    """
    Marque un professionnel comme verifie.

    Args:
        db: Session de base de donnees async
        professional_id: ID du professionnel
        current_user_id: ID Keycloak de l'admin verifiant

    Returns:
        ProfessionalResponse si verifie, None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("verify_professional") as span:
        span.set_attribute("professional.id", professional_id)

        result = await db.execute(
            select(ProfessionalGdprMetadata).where(
                ProfessionalGdprMetadata.id == professional_id,
                ProfessionalGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            return None

        gdpr_metadata.is_verified = True
        gdpr_metadata.updated_by = current_user_id
        gdpr_metadata.updated_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(gdpr_metadata)

        span.add_event("Professionnel verifie")

        # Publier evenement
        await publish(
            "identity.professional.verified",
            {
                "professional_id": gdpr_metadata.id,
                "fhir_resource_id": gdpr_metadata.fhir_resource_id,
                "keycloak_user_id": gdpr_metadata.keycloak_user_id,
                "verified_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # Fetch FHIR resource and return full response
        fhir_practitioner = await fhir_client.read("Practitioner", gdpr_metadata.fhir_resource_id)
        if not fhir_practitioner:
            return None

        return ProfessionalMapper.from_fhir(
            fhir_practitioner,
            gdpr_metadata.id,
            gdpr_metadata.to_dict(),
        )


async def toggle_availability(
    db: AsyncSession,
    professional_id: int,
    is_available: bool,
    current_user_id: str,
) -> ProfessionalResponse | None:
    """
    Change la disponibilite d'un professionnel pour consultations.

    Operation locale uniquement (is_available n'est pas dans FHIR standard).

    Args:
        db: Session de base de donnees async
        professional_id: ID du professionnel
        is_available: True pour disponible, False pour indisponible
        current_user_id: ID Keycloak

    Returns:
        ProfessionalResponse si mis a jour, None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("toggle_availability") as span:
        span.set_attribute("professional.id", professional_id)
        span.set_attribute("professional.is_available", is_available)

        result = await db.execute(
            select(ProfessionalGdprMetadata).where(
                ProfessionalGdprMetadata.id == professional_id,
                ProfessionalGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            return None

        gdpr_metadata.is_available = is_available
        gdpr_metadata.updated_by = current_user_id
        gdpr_metadata.updated_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(gdpr_metadata)

        span.add_event("Disponibilite mise a jour")

        # Publier evenement
        await publish(
            "identity.professional.availability_changed",
            {
                "professional_id": gdpr_metadata.id,
                "fhir_resource_id": gdpr_metadata.fhir_resource_id,
                "keycloak_user_id": gdpr_metadata.keycloak_user_id,
                "is_available": is_available,
                "changed_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # Fetch FHIR resource and return full response
        fhir_practitioner = await fhir_client.read("Practitioner", gdpr_metadata.fhir_resource_id)
        if not fhir_practitioner:
            return None

        return ProfessionalMapper.from_fhir(
            fhir_practitioner,
            gdpr_metadata.id,
            gdpr_metadata.to_dict(),
        )


async def get_professional_gdpr_metadata(
    db: AsyncSession,
    professional_id: int,
) -> ProfessionalGdprMetadata | None:
    """
    Recupere les metadonnees GDPR locales d'un professionnel.

    Utile pour les operations admin (enquete, anonymisation).

    Args:
        db: Session de base de donnees async
        professional_id: ID du professionnel

    Returns:
        ProfessionalGdprMetadata ou None
    """
    result = await db.execute(
        select(ProfessionalGdprMetadata).where(ProfessionalGdprMetadata.id == professional_id)
    )
    return result.scalar_one_or_none()


# =============================================================================
# Helper functions
# =============================================================================


def _extract_keycloak_id(fhir_practitioner: FHIRPractitioner) -> str | None:
    """Extrait le keycloak_user_id des identifiers FHIR."""
    if not fhir_practitioner.identifier:
        return None

    for identifier in fhir_practitioner.identifier:
        if identifier.system == KEYCLOAK_SYSTEM:
            return identifier.value

    return None


def _build_fhir_search_params(filters: ProfessionalSearchFilters) -> dict[str, str]:
    """Construit les parametres de recherche FHIR depuis les filtres."""
    params = {}

    if filters.first_name:
        params["given"] = filters.first_name
    if filters.last_name:
        params["family"] = filters.last_name
    if filters.professional_id:
        params["identifier"] = f"{PROFESSIONAL_LICENSE_SYSTEM}|{filters.professional_id}"
    if filters.specialty:
        params["qualification-code"] = filters.specialty
    if filters.facility_city:
        params["address-city"] = filters.facility_city
    if filters.facility_region:
        params["address-state"] = filters.facility_region
    if filters.is_active is not None:
        params["active"] = str(filters.is_active).lower()

    # Pagination FHIR
    params["_count"] = str(filters.limit)
    params["_offset"] = str(filters.skip)

    return params
