"""Endpoints administrateur pour gestion avancée des professionnels.

Ce module fournit des endpoints réservés aux administrateurs pour:
- Marquer/retirer statut d'enquête (blocage suppression)
- Restaurer professionnels soft deleted (pendant période de grâce)
- Lister professionnels en attente d'anonymisation
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.events import publish
from app.models.professional import Professional
from app.schemas.professional import (
    AnonymizationStatus,
    ProfessionalDeletionContext,
    ProfessionalResponse,
    ProfessionalRestoreRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/professionals", tags=["admin-professionals"])


@router.post("/{professional_id}/investigation", response_model=ProfessionalResponse)
async def mark_professional_under_investigation(
    professional_id: int,
    context: ProfessionalDeletionContext,
    db: AsyncSession = Depends(get_session),
) -> ProfessionalResponse:
    """
    Marque un professionnel comme sous enquête médico-légale.

    Bloque toute tentative de suppression tant que l'enquête est active.

    Args:
        professional_id: ID du professionnel
        context: Contexte avec notes d'enquête
        db: Session de base de données

    Returns:
        Professionnel mis à jour

    Raises:
        HTTPException 404: Professionnel non trouvé
    """
    # Récupérer professionnel
    professional = await db.get(Professional, professional_id)
    if not professional:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professional {professional_id} not found",
        )

    # Marquer sous enquête
    professional.under_investigation = True
    professional.investigation_notes = context.reason or "Enquête médico-légale en cours"
    professional.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(professional)

    # Publier événement
    await publish(
        "identity.professional.investigation_started",
        {
            "professional_id": professional.id,
            "keycloak_user_id": professional.keycloak_user_id,
            "investigation_notes": professional.investigation_notes,
            "marked_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(
        f"Professionnel {professional_id} marqué sous enquête: {professional.investigation_notes}"
    )

    return ProfessionalResponse.model_validate(professional)


@router.delete("/{professional_id}/investigation", response_model=ProfessionalResponse)
async def remove_investigation_status(
    professional_id: int,
    db: AsyncSession = Depends(get_session),
) -> ProfessionalResponse:
    """
    Retire le statut d'enquête d'un professionnel.

    Permet de nouveau la suppression du professionnel.

    Args:
        professional_id: ID du professionnel
        db: Session de base de données

    Returns:
        Professionnel mis à jour

    Raises:
        HTTPException 404: Professionnel non trouvé
    """
    # Récupérer professionnel
    professional = await db.get(Professional, professional_id)
    if not professional:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professional {professional_id} not found",
        )

    # Retirer enquête
    professional.under_investigation = False
    professional.investigation_notes = None
    professional.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(professional)

    # Publier événement
    await publish(
        "identity.professional.investigation_cleared",
        {
            "professional_id": professional.id,
            "keycloak_user_id": professional.keycloak_user_id,
            "cleared_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Professionnel {professional_id} enquête retirée")

    return ProfessionalResponse.model_validate(professional)


@router.post("/{professional_id}/restore", response_model=ProfessionalResponse)
async def restore_soft_deleted_professional(
    professional_id: int,
    restore_request: ProfessionalRestoreRequest,
    db: AsyncSession = Depends(get_session),
) -> ProfessionalResponse:
    """
    Restaure un professionnel soft deleted (pendant période de grâce).

    Impossible de restaurer si déjà anonymisé.

    Args:
        professional_id: ID du professionnel
        restore_request: Raison de la restauration
        db: Session de base de données

    Returns:
        Professionnel restauré

    Raises:
        HTTPException 404: Professionnel non trouvé
        HTTPException 422: Déjà anonymisé (impossible de restaurer)
    """
    # Récupérer professionnel
    professional = await db.get(Professional, professional_id)
    if not professional:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professional {professional_id} not found",
        )

    # Vérifier si anonymisé
    if professional.anonymized_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot restore professional {professional_id}: "
                "already anonymized. Anonymization is irreversible."
            ),
        )

    # Restaurer
    professional.is_active = True
    professional.soft_deleted_at = None
    professional.deletion_reason = None
    professional.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(professional)

    # Publier événement
    await publish(
        "identity.professional.restored",
        {
            "professional_id": professional.id,
            "keycloak_user_id": professional.keycloak_user_id,
            "restore_reason": restore_request.restore_reason,
            "restored_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Professionnel {professional_id} restauré: {restore_request.restore_reason}")

    return ProfessionalResponse.model_validate(professional)


@router.get("/deleted", response_model=list[AnonymizationStatus])
async def list_soft_deleted_professionals(
    db: AsyncSession = Depends(get_session),
) -> list[AnonymizationStatus]:
    """
    Liste tous les professionnels soft deleted en attente d'anonymisation.

    Retourne uniquement ceux dans la période de grâce (pas encore anonymisés).

    Args:
        db: Session de base de données

    Returns:
        Liste des professionnels soft deleted avec statut anonymisation
    """
    # Récupérer soft deleted (pas anonymisés)
    result = await db.execute(
        select(Professional).where(
            Professional.soft_deleted_at.isnot(None),
            Professional.anonymized_at.is_(None),
        )
    )
    professionals = result.scalars().all()

    # Convertir en AnonymizationStatus
    statuses = []
    for professional in professionals:
        status_obj = AnonymizationStatus(
            professional_id=professional.id,
            keycloak_user_id=professional.keycloak_user_id,
            email=professional.email,
            soft_deleted_at=professional.soft_deleted_at,
            anonymized_at=professional.anonymized_at,
            deletion_reason=professional.deletion_reason,
        )
        statuses.append(status_obj)

    logger.info(f"Listage {len(statuses)} professionnels soft deleted")

    return statuses
