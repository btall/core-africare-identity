"""Endpoints API pour la gestion des professionnels de santé.

Ce module définit tous les endpoints REST pour les opérations CRUD
et la recherche sur les professionnels de santé.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi_errors_rfc9457 import ConflictError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import User, get_current_user, require_roles
from app.schemas.professional import (
    ProfessionalCreate,
    ProfessionalListResponse,
    ProfessionalResponse,
    ProfessionalSearchFilters,
    ProfessionalUpdate,
)
from app.services import professional_service

router = APIRouter()


@router.post(
    "/",
    response_model=ProfessionalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un nouveau professionnel de santé",
    description="Crée un nouveau profil professionnel dans le système (admin seulement)",
)
async def create_professional(
    professional: ProfessionalCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_roles("admin")),
) -> ProfessionalResponse:
    """
    Crée un nouveau professionnel de santé.

    Permissions requises: JWT avec rôle 'admin'

    Note: La création automatique de profils professionnels depuis l'inscription Keycloak
    est gérée par le système de webhooks via Redis Streams, pas par cet endpoint.
    """
    try:
        created_professional = await professional_service.create_professional(
            db=db,
            professional_data=professional,
            current_user_id=current_user.sub,
        )
        return ProfessionalResponse.model_validate(created_professional)
    except IntegrityError as e:
        error_message = str(e)
        if "keycloak_user_id" in error_message:
            raise ConflictError(
                detail="Un professionnel existe déjà avec ce keycloak_user_id",
                instance="/api/v1/professionals",
            )
        if "professional_id" in error_message:
            raise ConflictError(
                detail="Un professionnel existe déjà avec ce numéro d'ordre",
                instance="/api/v1/professionals",
            )
        if "email" in error_message:
            raise ConflictError(
                detail="Un professionnel existe déjà avec cet email",
                instance="/api/v1/professionals",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Erreur lors de la création du professionnel",
        )


@router.get(
    "/{professional_id}",
    response_model=ProfessionalResponse,
    summary="Récupérer un professionnel par ID",
    description="Récupère les détails complets d'un professionnel par son ID",
)
async def get_professional(
    professional_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProfessionalResponse:
    """
    Récupère un professionnel par son ID.

    Permissions requises : Authenticated
    """
    professional = await professional_service.get_professional(
        db=db, professional_id=professional_id
    )
    if not professional:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professionnel avec ID {professional_id} non trouvé",
        )

    return ProfessionalResponse.model_validate(professional)


@router.get(
    "/keycloak/{keycloak_user_id}",
    response_model=ProfessionalResponse,
    summary="Récupérer un professionnel par Keycloak user ID",
    description="Récupère les détails d'un professionnel par son keycloak_user_id",
    dependencies=[Depends(require_roles("admin:technical", "professional"))],
)
async def get_professional_by_keycloak_id(
    keycloak_user_id: str,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProfessionalResponse:
    """
    Récupère un professionnel par son keycloak_user_id.

    Permet aux professionnels de récupérer leur propre profil.
    """
    professional = await professional_service.get_professional_by_keycloak_id(
        db=db,
        keycloak_user_id=keycloak_user_id,
    )
    if not professional:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professionnel avec keycloak_user_id {keycloak_user_id} non trouvé",
        )

    # TODO: Vérification RGPD + données d'audit
    # audit_data = current_user.verify_access(professional.keycloak_user_id)
    # TODO: await publish("audit.access", {
    #     "event_type": "professional_record_accessed",
    #     "resource_type": "professional",
    #     "resource_id": professional.id,
    #     "resource_owner_id": professional.keycloak_user_id,
    #     **audit_data,  # Spread: access_reason, accessed_by (UUID uniquement, minimisation RGPD)
    #     "timestamp": datetime.now(UTC).isoformat(),
    #     "ip_address": request.client.host,
    #     "user_agent": request.headers.get("user-agent"),
    # })

    return ProfessionalResponse.model_validate(professional)


@router.get(
    "/professional-id/{professional_id}",
    response_model=ProfessionalResponse,
    summary="Récupérer un professionnel par numéro d'ordre",
    description="Récupère un professionnel par son numéro d'ordre (CNOM, etc.)",
)
async def get_professional_by_professional_id(
    professional_id: str,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProfessionalResponse:
    """
    Récupère un professionnel par son numéro d'ordre professionnel.

    Permissions requises : Authenticated
    """
    professional = await professional_service.get_professional_by_professional_id(
        db=db,
        professional_id=professional_id,
    )
    if not professional:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professionnel avec numéro d'ordre {professional_id} non trouvé",
        )

    return ProfessionalResponse.model_validate(professional)


@router.put(
    "/{professional_id}",
    response_model=ProfessionalResponse,
    summary="Mettre à jour un professionnel",
    description="Met à jour les informations d'un professionnel existant",
    dependencies=[Depends(require_roles("admin:technical", "professional"))],
)
async def update_professional(
    professional_id: int,
    professional_update: ProfessionalUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProfessionalResponse:
    """
    Met à jour un professionnel existant.

    Permissions requises : Professional owner ou admin:technical
    """
    # Récupérer le professionnel existant pour vérification
    existing_professional = await professional_service.get_professional(
        db=db, professional_id=professional_id
    )
    if not existing_professional:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professionnel avec ID {professional_id} non trouvé",
        )

    # TODO: Vérification RGPD + données d'audit
    # audit_data = current_user.verify_access(existing_professional.keycloak_user_id)
    # TODO: await publish("audit.access", {
    #     "event_type": "professional_record_updated",
    #     "resource_type": "professional",
    #     "resource_id": professional_id,
    #     "resource_owner_id": existing_professional.keycloak_user_id,
    #     **audit_data,  # Spread: access_reason, accessed_by (UUID uniquement, minimisation RGPD)
    #     "timestamp": datetime.now(UTC).isoformat(),
    #     "ip_address": request.client.host,
    #     "user_agent": request.headers.get("user-agent"),
    # })

    updated_professional = await professional_service.update_professional(
        db=db,
        professional_id=professional_id,
        professional_data=professional_update,
        current_user_id=current_user.sub,
    )

    return ProfessionalResponse.model_validate(updated_professional)


@router.delete(
    "/{professional_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un professionnel (soft delete)",
    description="Marque un professionnel comme inactif (soft delete)",
    dependencies=[Depends(require_roles("admin"))],
)
async def delete_professional(
    professional_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Supprime un professionnel (soft delete).

    Permissions requises : admin uniquement
    """
    deleted = await professional_service.delete_professional(
        db=db,
        professional_id=professional_id,
        current_user_id=current_user.sub,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professionnel avec ID {professional_id} non trouvé",
        )


@router.get(
    "/",
    response_model=ProfessionalListResponse,
    summary="Rechercher des professionnels",
    description="Recherche des professionnels avec filtres et pagination",
)
async def search_professionals(
    first_name: str | None = Query(None, description="Filtrer par prénom"),
    last_name: str | None = Query(None, description="Filtrer par nom"),
    professional_id: str | None = Query(None, description="Filtrer par numéro d'ordre"),
    specialty: str | None = Query(None, description="Filtrer par spécialité"),
    professional_type: str | None = Query(None, description="Filtrer par type"),
    facility_name: str | None = Query(None, description="Filtrer par établissement"),
    facility_city: str | None = Query(None, description="Filtrer par ville"),
    facility_region: str | None = Query(None, description="Filtrer par région"),
    is_active: bool | None = Query(None, description="Filtrer par statut actif"),
    is_verified: bool | None = Query(None, description="Filtrer par vérification"),
    is_available: bool | None = Query(None, description="Filtrer par disponibilité"),
    skip: int = Query(0, ge=0, description="Nombre d'éléments à sauter"),
    limit: int = Query(20, ge=1, le=100, description="Nombre d'éléments à retourner"),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProfessionalListResponse:
    """
    Recherche des professionnels avec filtres et pagination.

    Permissions requises : authenticated
    """
    # Construire les filtres
    filters = ProfessionalSearchFilters(
        first_name=first_name,
        last_name=last_name,
        professional_id=professional_id,
        specialty=specialty,
        professional_type=professional_type,
        facility_name=facility_name,
        facility_city=facility_city,
        facility_region=facility_region,
        is_active=is_active,
        is_verified=is_verified,
        is_available=is_available,
        skip=skip,
        limit=limit,
    )

    # Rechercher
    professionals, total = await professional_service.search_professionals(db=db, filters=filters)

    return ProfessionalListResponse(
        items=professionals,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/{professional_id}/verify",
    response_model=ProfessionalResponse,
    summary="Vérifier un professionnel",
    description="Marque un professionnel comme vérifié par un administrateur",
    dependencies=[Depends(require_roles("admin"))],
)
async def verify_professional(
    professional_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProfessionalResponse:
    """
    Marque un professionnel comme vérifié.

    Permissions requises : admin uniquement
    """
    verified_professional = await professional_service.verify_professional(
        db=db,
        professional_id=professional_id,
        current_user_id=current_user.sub,
    )

    if not verified_professional:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professionnel avec ID {professional_id} non trouvé",
        )

    return ProfessionalResponse.model_validate(verified_professional)


@router.post(
    "/{professional_id}/availability",
    response_model=ProfessionalResponse,
    summary="Changer la disponibilité",
    description="Change la disponibilité d'un professionnel pour consultations",
    dependencies=[Depends(require_roles("admin:technical", "professional"))],
)
async def toggle_availability(
    professional_id: int,
    is_available: bool = Query(..., description="Disponible (true) ou indisponible (false)"),
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ProfessionalResponse:
    """
    Change la disponibilité d'un professionnel.

    Permissions requises : Professional owner ou admin:technical
    """
    # Récupérer le professionnel pour vérification
    professional = await professional_service.get_professional(
        db=db, professional_id=professional_id
    )
    if not professional:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professionnel avec ID {professional_id} non trouvé",
        )

    # TODO: Vérification RGPD + données d'audit
    # audit_data = current_user.verify_access(professional.keycloak_user_id)
    # TODO: await publish("audit.access", {
    #     "event_type": "professional_availability_updated",
    #     "resource_type": "professional",
    #     "resource_id": professional_id,
    #     "resource_owner_id": professional.keycloak_user_id,
    #     **audit_data,  # Spread: access_reason, accessed_by (UUID uniquement, minimisation RGPD)
    #     "timestamp": datetime.now(UTC).isoformat(),
    #     "ip_address": request.client.host,
    #     "user_agent": request.headers.get("user-agent"),
    # })

    updated_professional = await professional_service.toggle_availability(
        db=db,
        professional_id=professional_id,
        is_available=is_available,
        current_user_id=current_user.sub,
    )

    return ProfessionalResponse.model_validate(updated_professional)
