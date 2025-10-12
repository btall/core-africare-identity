"""Endpoints API pour la gestion des patients.

Ce module définit tous les endpoints REST pour les opérations CRUD
et la recherche sur les patients.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import get_current_user
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
)
async def create_patient(
    patient: PatientCreate,
    db: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> PatientResponse:
    """
    Crée un nouveau patient.

    Permissions requises : role 'admin' ou 'professional'
    """
    try:
        created_patient = await patient_service.create_patient(
            db=db,
            patient_data=patient,
            current_user_id=current_user["sub"],
        )
        return PatientResponse.model_validate(created_patient)
    except IntegrityError as e:
        if "keycloak_user_id" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Un patient existe déjà avec ce keycloak_user_id",
            )
        if "national_id" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Un patient existe déjà avec cet identifiant national",
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
    current_user: dict = Depends(get_current_user),
) -> PatientResponse:
    """
    Récupère un patient par son ID.

    Permissions requises : Authenticated
    """
    patient = await patient_service.get_patient(db=db, patient_id=patient_id)
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
)
async def get_patient_by_keycloak_id(
    keycloak_user_id: str,
    db: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> PatientResponse:
    """
    Récupère un patient par son keycloak_user_id.

    Permet aux patients de récupérer leur propre profil.
    """
    patient = await patient_service.get_patient_by_keycloak_id(
        db=db,
        keycloak_user_id=keycloak_user_id,
    )
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient avec keycloak_user_id {keycloak_user_id} non trouvé",
        )

    # Vérifier que l'utilisateur accède à son propre profil ou est admin/professional
    if (
        patient.keycloak_user_id != current_user["sub"]
        and "admin" not in current_user.get("realm_access", {}).get("roles", [])
        and "professional" not in current_user.get("realm_access", {}).get("roles", [])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à ce profil patient",
        )

    return PatientResponse.model_validate(patient)


@router.put(
    "/{patient_id}",
    response_model=PatientResponse,
    summary="Mettre à jour un patient",
    description="Met à jour les informations d'un patient existant",
)
async def update_patient(
    patient_id: int,
    patient_update: PatientUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> PatientResponse:
    """
    Met à jour un patient existant.

    Permissions requises : Patient owner, admin ou professional
    """
    # Récupérer le patient existant pour vérification
    existing_patient = await patient_service.get_patient(db=db, patient_id=patient_id)
    if not existing_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient avec ID {patient_id} non trouvé",
        )

    # Vérifier les permissions
    if (
        existing_patient.keycloak_user_id != current_user["sub"]
        and "admin" not in current_user.get("realm_access", {}).get("roles", [])
        and "professional" not in current_user.get("realm_access", {}).get("roles", [])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé pour modifier ce profil patient",
        )

    updated_patient = await patient_service.update_patient(
        db=db,
        patient_id=patient_id,
        patient_data=patient_update,
        current_user_id=current_user["sub"],
    )

    return PatientResponse.model_validate(updated_patient)


@router.delete(
    "/{patient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un patient (soft delete)",
    description="Marque un patient comme inactif (soft delete)",
)
async def delete_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> None:
    """
    Supprime un patient (soft delete).

    Permissions requises : admin uniquement
    """
    # Vérifier le rôle admin
    if "admin" not in current_user.get("realm_access", {}).get("roles", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seuls les administrateurs peuvent supprimer des patients",
        )

    deleted = await patient_service.delete_patient(
        db=db,
        patient_id=patient_id,
        current_user_id=current_user["sub"],
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
    current_user: dict = Depends(get_current_user),
) -> PatientListResponse:
    """
    Recherche des patients avec filtres et pagination.

    Permissions requises : admin ou professional
    """
    # Vérifier les permissions
    if (
        "admin" not in current_user.get("realm_access", {}).get("roles", [])
        and "professional" not in current_user.get("realm_access", {}).get("roles", [])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé à la liste des patients",
        )

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
    patients, total = await patient_service.search_patients(db=db, filters=filters)

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
)
async def verify_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: dict = Depends(get_current_user),
) -> PatientResponse:
    """
    Marque un patient comme vérifié.

    Permissions requises : professional ou admin
    """
    # Vérifier les permissions
    if (
        "admin" not in current_user.get("realm_access", {}).get("roles", [])
        and "professional" not in current_user.get("realm_access", {}).get("roles", [])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seuls les professionnels de santé peuvent vérifier des patients",
        )

    verified_patient = await patient_service.verify_patient(
        db=db,
        patient_id=patient_id,
        current_user_id=current_user["sub"],
    )

    if not verified_patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient avec ID {patient_id} non trouvé",
        )

    return PatientResponse.model_validate(verified_patient)
