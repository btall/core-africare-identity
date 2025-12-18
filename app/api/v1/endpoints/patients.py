"""Endpoints API pour la gestion des patients.

Ce module définit tous les endpoints REST pour les opérations CRUD
et la recherche sur les patients.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi_errors_rfc9457 import ConflictError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import get_fhir_client
from app.core.security import User, get_current_user, require_roles
from app.infrastructure.fhir.client import FHIRClient
from app.schemas.patient import (
    PatientCreate,
    PatientListResponse,
    PatientResponse,
    PatientSearchFilters,
    PatientUpdate,
)
from app.services import patient_service

router = APIRouter()


@router.post(
    "/",
    response_model=PatientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un nouveau patient",
    description="Crée un nouveau profil patient dans le système",
    dependencies=[Depends(require_roles("admin", "professional"))],
)
async def create_patient(
    patient: PatientCreate,
    db: AsyncSession = Depends(get_session),
    fhir_client: FHIRClient = Depends(get_fhir_client),
    current_user: User = Depends(get_current_user),
) -> PatientResponse:
    """
    Crée un nouveau patient.

    Permissions requises : role 'admin' ou 'professional'
    """
    try:
        created_patient = await patient_service.create_patient(
            db=db,
            fhir_client=fhir_client,
            patient_data=patient,
            current_user_id=current_user.user_id,
        )
        return PatientResponse.model_validate(created_patient)
    except IntegrityError as e:
        error_message = str(e)
        if "keycloak_user_id" in error_message:
            raise ConflictError(
                detail="Un patient existe déjà avec ce keycloak_user_id",
                instance="/api/v1/patients",
            )
        if "national_id" in error_message:
            raise ConflictError(
                detail="Un patient existe déjà avec cet identifiant national",
                instance="/api/v1/patients",
            )
        if "email" in error_message:
            raise ConflictError(
                detail="Un patient existe déjà avec cet email",
                instance="/api/v1/patients",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Erreur lors de la création du patient",
        )


@router.get(
    "/{patient_id}",
    response_model=PatientResponse,
    summary="Récupérer un patient par ID",
    description="Récupère les détails complets d'un patient par son ID",
)
async def get_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_session),
    fhir_client: FHIRClient = Depends(get_fhir_client),
    current_user: User = Depends(get_current_user),
) -> PatientResponse:
    """
    Récupère un patient par son ID.

    Permissions requises : Authenticated
    """
    patient = await patient_service.get_patient(
        db=db, fhir_client=fhir_client, patient_id=patient_id
    )
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient avec ID {patient_id} non trouvé",
        )

    return PatientResponse.model_validate(patient)


@router.get(
    "/keycloak/{keycloak_user_id}",
    response_model=PatientResponse,
    summary="Récupérer un patient par Keycloak user ID",
    description="Récupère les détails d'un patient par son keycloak_user_id",
    dependencies=[Depends(require_roles("admin:medical", "professional", "patient"))],
)
async def get_patient_by_keycloak_id(
    keycloak_user_id: str,
    db: AsyncSession = Depends(get_session),
    fhir_client: FHIRClient = Depends(get_fhir_client),
    current_user: User = Depends(get_current_user),
) -> PatientResponse:
    """
    Récupère un patient par son keycloak_user_id.

    Permet aux patients de récupérer leur propre profil.
    """
    patient = await patient_service.get_patient_by_keycloak_id(
        db=db,
        fhir_client=fhir_client,
        keycloak_user_id=keycloak_user_id,
    )
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient avec keycloak_user_id {keycloak_user_id} non trouvé",
        )

    # TODO: Vérification RGPD + données d'audit
    # audit_data = current_user.verify_access(patient.keycloak_user_id)
    # TODO: await publish("audit.access", {
    #     "event_type": "patient_record_accessed",
    #     "resource_type": "patient",
    #     "resource_id": patient.id,
    #     "resource_owner_id": patient.keycloak_user_id,
    #     **audit_data,  # Spread: access_reason, accessed_by (UUID uniquement, minimisation RGPD)
    #     "timestamp": datetime.now(UTC).isoformat(),
    #     "ip_address": request.client.host,
    #     "user_agent": request.headers.get("user-agent"),
    # })

    return PatientResponse.model_validate(patient)


@router.put(
    "/{patient_id}",
    response_model=PatientResponse,
    summary="Mettre à jour un patient",
    description="Met à jour les informations d'un patient existant",
    dependencies=[Depends(require_roles("admin:medical", "professional", "patient"))],
)
async def update_patient(
    patient_id: int,
    patient_update: PatientUpdate,
    db: AsyncSession = Depends(get_session),
    fhir_client: FHIRClient = Depends(get_fhir_client),
    current_user: User = Depends(get_current_user),
) -> PatientResponse:
    """
    Met à jour un patient existant.

    Permissions requises : Patient owner, admin:medical ou professional
    """
    # Récupérer le patient existant pour vérification
    existing_patient = await patient_service.get_patient(
        db=db, fhir_client=fhir_client, patient_id=patient_id
    )
    if not existing_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient avec ID {patient_id} non trouvé",
        )

    # TODO: Vérification RGPD + données d'audit
    # audit_data = current_user.verify_access(existing_patient.keycloak_user_id)
    # TODO: await publish("audit.access", {
    #     "event_type": "patient_record_updated",
    #     "resource_type": "patient",
    #     "resource_id": patient_id,
    #     "resource_owner_id": existing_patient.keycloak_user_id,
    #     **audit_data,  # Spread: access_reason, accessed_by (UUID uniquement, minimisation RGPD)
    #     "timestamp": datetime.now(UTC).isoformat(),
    #     "ip_address": request.client.host,
    #     "user_agent": request.headers.get("user-agent"),
    # })

    updated_patient = await patient_service.update_patient(
        db=db,
        fhir_client=fhir_client,
        patient_id=patient_id,
        patient_data=patient_update,
        current_user_id=current_user.user_id,
    )

    return PatientResponse.model_validate(updated_patient)


@router.delete(
    "/{patient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un patient (soft delete)",
    description="Marque un patient comme inactif (soft delete)",
    dependencies=[Depends(require_roles("admin"))],
)
async def delete_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_session),
    fhir_client: FHIRClient = Depends(get_fhir_client),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Supprime un patient (soft delete).

    Permissions requises : admin uniquement
    """
    deleted = await patient_service.delete_patient(
        db=db,
        fhir_client=fhir_client,
        patient_id=patient_id,
        current_user_id=current_user.user_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient avec ID {patient_id} non trouvé",
        )


@router.get(
    "/",
    response_model=PatientListResponse,
    summary="Rechercher des patients",
    description="Recherche des patients avec filtres et pagination",
    dependencies=[Depends(require_roles("admin", "professional"))],
)
async def search_patients(
    first_name: str | None = Query(None, description="Filtrer par prénom"),
    last_name: str | None = Query(None, description="Filtrer par nom"),
    national_id: str | None = Query(None, description="Filtrer par ID national"),
    email: str | None = Query(None, description="Filtrer par email"),
    phone: str | None = Query(None, description="Filtrer par téléphone"),
    gender: str | None = Query(None, description="Filtrer par sexe"),
    is_active: bool | None = Query(None, description="Filtrer par statut actif"),
    is_verified: bool | None = Query(None, description="Filtrer par vérification"),
    region: str | None = Query(None, description="Filtrer par région"),
    city: str | None = Query(None, description="Filtrer par ville"),
    skip: int = Query(0, ge=0, description="Nombre d'éléments à sauter"),
    limit: int = Query(20, ge=1, le=100, description="Nombre d'éléments à retourner"),
    db: AsyncSession = Depends(get_session),
    fhir_client: FHIRClient = Depends(get_fhir_client),
    current_user: User = Depends(get_current_user),
) -> PatientListResponse:
    """
    Recherche des patients avec filtres et pagination.

    Permissions requises : admin ou professional
    """
    # Construire les filtres
    filters = PatientSearchFilters(
        first_name=first_name,
        last_name=last_name,
        national_id=national_id,
        email=email,
        phone=phone,
        gender=gender,
        is_active=is_active,
        is_verified=is_verified,
        region=region,
        city=city,
        skip=skip,
        limit=limit,
    )

    # Rechercher
    patients, total = await patient_service.search_patients(
        db=db, fhir_client=fhir_client, filters=filters
    )

    return PatientListResponse(
        items=patients,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/{patient_id}/verify",
    response_model=PatientResponse,
    summary="Vérifier un patient",
    description="Marque un patient comme vérifié par un professionnel de santé",
    dependencies=[Depends(require_roles("admin", "professional"))],
)
async def verify_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_session),
    fhir_client: FHIRClient = Depends(get_fhir_client),
    current_user: User = Depends(get_current_user),
) -> PatientResponse:
    """
    Marque un patient comme vérifié.

    Permissions requises : professional ou admin
    """
    verified_patient = await patient_service.verify_patient(
        db=db,
        fhir_client=fhir_client,
        patient_id=patient_id,
        current_user_id=current_user.user_id,
    )

    if not verified_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient avec ID {patient_id} non trouvé",
        )

    return PatientResponse.model_validate(verified_patient)
