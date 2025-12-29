"""Service metier pour la gestion des patients.

Ce module implemente la logique metier pour les operations CRUD
sur les patients avec architecture hybride:
- HAPI FHIR: Source de verite pour donnees demographiques
- PostgreSQL: Metadonnees GDPR locales
"""

from datetime import UTC, datetime

from fhir.resources.patient import Patient as FHIRPatient
from opentelemetry import trace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get, cache_key_patient, cache_set
from app.core.config import settings
from app.core.events import publish
from app.infrastructure.fhir.client import get_fhir_client
from app.infrastructure.fhir.exceptions import FHIRResourceNotFoundError
from app.infrastructure.fhir.identifiers import KEYCLOAK_SYSTEM, NATIONAL_ID_SYSTEM
from app.infrastructure.fhir.mappers.patient_mapper import PatientMapper
from app.models.gdpr_metadata import PatientGdprMetadata
from app.schemas.patient import (
    PatientCreate,
    PatientListItem,
    PatientResponse,
    PatientSearchFilters,
    PatientUpdate,
)

tracer = trace.get_tracer(__name__)


async def create_patient(
    db: AsyncSession,
    patient_data: PatientCreate,
    current_user_id: str,
) -> PatientResponse:
    """
    Cree un nouveau patient dans FHIR et les metadonnees locales.

    Pattern d'orchestration:
    1. Mapper vers FHIR Patient
    2. Creer dans HAPI FHIR
    3. Creer metadonnees GDPR locales
    4. Publier evenement
    5. Retourner response avec ID numerique

    Args:
        db: Session de base de donnees async
        patient_data: Donnees du patient a creer
        current_user_id: ID Keycloak de l'utilisateur createur

    Returns:
        PatientResponse avec ID numerique local

    Raises:
        FHIROperationError: Si creation FHIR echoue
        IntegrityError: Si keycloak_user_id existe deja
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("create_patient") as span:
        span.set_attribute("patient.keycloak_user_id", patient_data.keycloak_user_id)

        # 1. Mapper vers FHIR Patient
        fhir_patient = PatientMapper.to_fhir(patient_data)

        # 2. Creer dans HAPI FHIR
        created_fhir: FHIRPatient = await fhir_client.create(fhir_patient)
        span.set_attribute("fhir.resource_id", created_fhir.id)

        # 3. Creer metadonnees GDPR locales
        gdpr_metadata = PatientGdprMetadata(
            fhir_resource_id=created_fhir.id,
            keycloak_user_id=patient_data.keycloak_user_id,
            is_verified=False,
            notes=None,
            created_by=current_user_id,
            updated_by=current_user_id,
        )
        db.add(gdpr_metadata)
        await db.commit()
        await db.refresh(gdpr_metadata)

        span.set_attribute("patient.id", gdpr_metadata.id)
        span.add_event("Patient cree avec succes")

        # 4. Publier evenement
        await publish(
            "identity.patient.created",
            {
                "patient_id": gdpr_metadata.id,
                "fhir_resource_id": created_fhir.id,
                "keycloak_user_id": patient_data.keycloak_user_id,
                "first_name": patient_data.first_name,
                "last_name": patient_data.last_name,
                "created_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # 5. Retourner response avec ID numerique
        return PatientMapper.from_fhir(
            created_fhir,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )


async def get_patient(
    db: AsyncSession,
    patient_id: int,
) -> PatientResponse | None:
    """
    Recupere un patient par son ID numerique local.

    Pattern (avec cache):
    1. Verifier cache Redis
    2. Si miss: Lookup local pour obtenir fhir_resource_id
    3. Fetch depuis HAPI FHIR
    4. Combiner avec metadonnees GDPR
    5. Mettre en cache

    Args:
        db: Session de base de donnees async
        patient_id: ID numerique du patient

    Returns:
        PatientResponse ou None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("get_patient") as span:
        span.set_attribute("patient.id", patient_id)

        # 1. Verifier cache Redis
        cache_key = cache_key_patient(patient_id)
        cached_json = await cache_get(cache_key)
        if cached_json:
            span.add_event("Cache HIT")
            return PatientResponse.model_validate_json(cached_json)

        # 2. Cache MISS - Lookup local
        result = await db.execute(
            select(PatientGdprMetadata).where(
                PatientGdprMetadata.id == patient_id,
                PatientGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            span.add_event("Patient non trouve (local)")
            return None

        # 3. Fetch depuis HAPI FHIR
        fhir_patient = await fhir_client.read("Patient", gdpr_metadata.fhir_resource_id)
        if not fhir_patient:
            span.add_event("Patient non trouve (FHIR)")
            return None

        span.add_event("Patient trouve")

        # 4. Combiner avec metadonnees GDPR
        response = PatientMapper.from_fhir(
            fhir_patient,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )

        # 5. Mettre en cache
        await cache_set(cache_key, response.model_dump_json(), ttl=settings.CACHE_TTL_PATIENT)

        return response


async def get_patient_by_keycloak_id(
    db: AsyncSession,
    keycloak_user_id: str,
) -> PatientResponse | None:
    """
    Recupere un patient par son keycloak_user_id.

    Args:
        db: Session de base de donnees async
        keycloak_user_id: UUID Keycloak de l'utilisateur

    Returns:
        PatientResponse ou None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("get_patient_by_keycloak_id") as span:
        span.set_attribute("patient.keycloak_user_id", keycloak_user_id)

        # Lookup local par keycloak_user_id
        result = await db.execute(
            select(PatientGdprMetadata).where(
                PatientGdprMetadata.keycloak_user_id == keycloak_user_id,
                PatientGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            span.add_event("Patient non trouve")
            return None

        # Fetch depuis FHIR
        fhir_patient = await fhir_client.read("Patient", gdpr_metadata.fhir_resource_id)
        if not fhir_patient:
            return None

        span.set_attribute("patient.id", gdpr_metadata.id)
        span.add_event("Patient trouve")

        return PatientMapper.from_fhir(
            fhir_patient,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )


async def get_patient_by_national_id(
    db: AsyncSession,
    national_id: str,
) -> PatientResponse | None:
    """
    Recupere un patient par son identifiant national via FHIR search.

    Args:
        db: Session de base de donnees async
        national_id: Identifiant national (CNI, passeport, etc.)

    Returns:
        PatientResponse ou None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("get_patient_by_national_id") as span:
        span.set_attribute("patient.national_id", national_id)

        # Recherche FHIR par identifier
        fhir_patient = await fhir_client.search_by_identifier(
            "Patient", NATIONAL_ID_SYSTEM, national_id
        )

        if not fhir_patient:
            span.add_event("Patient non trouve (FHIR)")
            return None

        # Lookup local pour obtenir ID et metadonnees
        keycloak_id = _extract_keycloak_id(fhir_patient)
        if not keycloak_id:
            return None

        result = await db.execute(
            select(PatientGdprMetadata).where(
                PatientGdprMetadata.keycloak_user_id == keycloak_id,
                PatientGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            return None

        span.set_attribute("patient.id", gdpr_metadata.id)
        span.add_event("Patient trouve")

        return PatientMapper.from_fhir(
            fhir_patient,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )


async def update_patient(
    db: AsyncSession,
    patient_id: int,
    patient_data: PatientUpdate,
    current_user_id: str,
) -> PatientResponse | None:
    """
    Met a jour un patient existant.

    Pattern:
    1. Lookup local
    2. Fetch FHIR Patient
    3. Appliquer updates via mapper
    4. Update dans FHIR
    5. Update metadonnees locales
    6. Publier evenement

    Args:
        db: Session de base de donnees async
        patient_id: ID du patient a mettre a jour
        patient_data: Nouvelles donnees du patient
        current_user_id: ID Keycloak de l'utilisateur modificateur

    Returns:
        PatientResponse mis a jour ou None si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("update_patient") as span:
        span.set_attribute("patient.id", patient_id)

        # 1. Lookup local
        result = await db.execute(
            select(PatientGdprMetadata).where(
                PatientGdprMetadata.id == patient_id,
                PatientGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            span.add_event("Patient non trouve")
            return None

        # 2. Fetch FHIR Patient
        fhir_patient = await fhir_client.read("Patient", gdpr_metadata.fhir_resource_id)
        if not fhir_patient:
            return None

        # 3. Appliquer updates via mapper
        updated_fhir = PatientMapper.apply_updates(fhir_patient, patient_data)

        # 4. Update dans FHIR
        try:
            updated_fhir = await fhir_client.update(updated_fhir)
        except FHIRResourceNotFoundError:
            return None

        # 5. Update metadonnees locales
        gdpr_metadata.updated_by = current_user_id
        gdpr_metadata.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(gdpr_metadata)

        span.add_event("Patient mis a jour avec succes")

        # 6. Publier evenement
        await publish(
            "identity.patient.updated",
            {
                "patient_id": gdpr_metadata.id,
                "fhir_resource_id": gdpr_metadata.fhir_resource_id,
                "keycloak_user_id": gdpr_metadata.keycloak_user_id,
                "updated_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        return PatientMapper.from_fhir(
            updated_fhir,
            local_id=gdpr_metadata.id,
            gdpr_metadata=gdpr_metadata.to_dict(),
        )


async def delete_patient(
    db: AsyncSession,
    patient_id: int,
    current_user_id: str,
    deletion_reason: str = "user_request",
) -> bool:
    """
    Soft delete un patient (RGPD compliant).

    Pattern:
    1. Marquer metadonnees locales comme supprimees
    2. Desactiver ressource FHIR (active=false)
    3. Publier evenement

    Note: L'anonymisation definitive se fait apres periode de grace (7 jours).

    Args:
        db: Session de base de donnees async
        patient_id: ID du patient a supprimer
        current_user_id: ID Keycloak de l'utilisateur
        deletion_reason: Raison de la suppression

    Returns:
        True si supprime, False si non trouve
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("delete_patient") as span:
        span.set_attribute("patient.id", patient_id)

        # Lookup local
        result = await db.execute(
            select(PatientGdprMetadata).where(
                PatientGdprMetadata.id == patient_id,
                PatientGdprMetadata.soft_deleted_at.is_(None),
            )
        )
        gdpr_metadata = result.scalar_one_or_none()

        if not gdpr_metadata:
            span.add_event("Patient non trouve")
            return False

        # Verifier si sous enquete
        if gdpr_metadata.under_investigation:
            span.add_event("Patient sous enquete - suppression bloquee")
            return False

        # 1. Marquer localement comme supprime
        gdpr_metadata.soft_deleted_at = datetime.now(UTC)
        gdpr_metadata.deleted_by = current_user_id
        gdpr_metadata.deletion_reason = deletion_reason
        gdpr_metadata.updated_by = current_user_id
        gdpr_metadata.updated_at = datetime.now(UTC)

        # 2. Desactiver dans FHIR
        fhir_patient = await fhir_client.read("Patient", gdpr_metadata.fhir_resource_id)
        if fhir_patient:
            fhir_patient.active = False
            await fhir_client.update(fhir_patient)

        await db.commit()

        span.add_event("Patient desactive (soft delete)")

        # 3. Publier evenement
        await publish(
            "identity.patient.deactivated",
            {
                "patient_id": gdpr_metadata.id,
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


async def search_patients(
    db: AsyncSession,
    filters: PatientSearchFilters,
) -> tuple[list[PatientListItem], int]:
    """
    Recherche des patients selon des criteres de filtrage.

    Strategie hybride:
    - Filtres demographiques: FHIR search
    - Filtres GDPR (is_verified): Local join

    Args:
        db: Session de base de donnees async
        filters: Criteres de recherche et pagination

    Returns:
        Tuple (liste des patients, nombre total de resultats)
    """
    fhir_client = get_fhir_client()
    with tracer.start_as_current_span("search_patients") as span:
        # Construire params FHIR
        fhir_params = _build_fhir_search_params(filters)

        # Recherche FHIR
        bundle = await fhir_client.search("Patient", params=fhir_params)
        total_fhir = bundle.total or 0

        if not bundle.entry:
            span.set_attribute("search.total_results", 0)
            return [], 0

        # Extraire keycloak_ids pour lookup local
        fhir_patients = {}
        keycloak_ids = []
        for entry in bundle.entry:
            if entry.resource:
                patient = entry.resource
                keycloak_id = _extract_keycloak_id(patient)
                if keycloak_id:
                    fhir_patients[keycloak_id] = patient
                    keycloak_ids.append(keycloak_id)

        # Lookup local pour metadonnees et IDs
        local_query = select(PatientGdprMetadata).where(
            PatientGdprMetadata.keycloak_user_id.in_(keycloak_ids),
            PatientGdprMetadata.soft_deleted_at.is_(None),
        )

        # Appliquer filtres locaux
        if filters.is_verified is not None:
            local_query = local_query.where(PatientGdprMetadata.is_verified == filters.is_verified)

        local_result = await db.execute(local_query)
        gdpr_records = {r.keycloak_user_id: r for r in local_result.scalars().all()}

        # Combiner resultats
        patient_items = []
        for keycloak_id, fhir_patient in fhir_patients.items():
            gdpr = gdpr_records.get(keycloak_id)
            if gdpr:
                item = PatientMapper.to_list_item(
                    fhir_patient,
                    local_id=gdpr.id,
                    gdpr_metadata=gdpr.to_dict(),
                )
                patient_items.append(item)

        # Compter total avec filtres locaux si appliques
        if filters.is_verified is not None:
            count_query = select(func.count()).select_from(
                select(PatientGdprMetadata)
                .where(
                    PatientGdprMetadata.soft_deleted_at.is_(None),
                    PatientGdprMetadata.is_verified == filters.is_verified,
                )
                .subquery()
            )
            count_result = await db.execute(count_query)
            total = min(count_result.scalar_one(), total_fhir)
        else:
            total = total_fhir

        span.set_attribute("search.total_results", total)
        span.set_attribute("search.returned_results", len(patient_items))
        span.add_event("Recherche terminee")

        return patient_items, total


async def verify_patient(
    db: AsyncSession,
    patient_id: int,
    current_user_id: str,
) -> PatientResponse | None:
    """
    Marque un patient comme verifie (operation locale uniquement).

    Args:
        db: Session de base de donnees async
        patient_id: ID du patient
        current_user_id: ID Keycloak du professionnel verifiant

    Returns:
        PatientResponse verifie ou None si non trouve
    """
    with tracer.start_as_current_span("verify_patient") as span:
        span.set_attribute("patient.id", patient_id)

        result = await db.execute(
            select(PatientGdprMetadata).where(
                PatientGdprMetadata.id == patient_id,
                PatientGdprMetadata.soft_deleted_at.is_(None),
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

        span.add_event("Patient verifie")

        # Publier evenement
        await publish(
            "identity.patient.verified",
            {
                "patient_id": gdpr_metadata.id,
                "fhir_resource_id": gdpr_metadata.fhir_resource_id,
                "keycloak_user_id": gdpr_metadata.keycloak_user_id,
                "verified_by": current_user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        # Note: On ne retourne pas les donnees FHIR ici car c'est une operation locale
        # L'appelant doit faire un get_patient() si besoin des donnees completes
        return None


async def get_patient_gdpr_metadata(
    db: AsyncSession,
    patient_id: int,
) -> PatientGdprMetadata | None:
    """
    Recupere les metadonnees GDPR locales d'un patient.

    Utile pour les operations admin (enquete, anonymisation).

    Args:
        db: Session de base de donnees async
        patient_id: ID du patient

    Returns:
        PatientGdprMetadata ou None
    """
    result = await db.execute(
        select(PatientGdprMetadata).where(PatientGdprMetadata.id == patient_id)
    )
    return result.scalar_one_or_none()


# =============================================================================
# Helper functions
# =============================================================================


def _extract_keycloak_id(fhir_patient: FHIRPatient) -> str | None:
    """Extrait le keycloak_user_id des identifiers FHIR."""
    if not fhir_patient.identifier:
        return None

    for identifier in fhir_patient.identifier:
        if identifier.system == KEYCLOAK_SYSTEM:
            return identifier.value

    return None


def _build_fhir_search_params(filters: PatientSearchFilters) -> dict[str, str]:
    """Construit les parametres de recherche FHIR depuis les filtres."""
    params = {}

    if filters.first_name:
        params["given"] = filters.first_name
    if filters.last_name:
        params["family"] = filters.last_name
    if filters.national_id:
        params["identifier"] = f"{NATIONAL_ID_SYSTEM}|{filters.national_id}"
    if filters.email:
        params["email"] = filters.email
    if filters.phone:
        params["phone"] = filters.phone
    if filters.gender:
        params["gender"] = filters.gender
    if filters.is_active is not None:
        params["active"] = str(filters.is_active).lower()
    if filters.city:
        params["address-city"] = filters.city
    if filters.region:
        params["address-state"] = filters.region

    # Pagination FHIR
    params["_count"] = str(filters.limit)
    params["_offset"] = str(filters.skip)

    return params
