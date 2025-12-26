"""Endpoints administrateur pour gestion avancée des professionnels.

Ce module fournit des endpoints réservés aux administrateurs pour:
- Marquer/retirer statut d'enquête (blocage suppression)
- Restaurer professionnels soft deleted (pendant période de grâce)
- Lister professionnels en attente d'anonymisation

Architecture hybride FHIR + PostgreSQL:
- Données démographiques: HAPI FHIR (Practitioner resource)
- Métadonnées GDPR: PostgreSQL (professional_gdpr_metadata table)
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.events import publish
from app.infrastructure.fhir.client import get_fhir_client
from app.infrastructure.fhir.identifiers import KEYCLOAK_SYSTEM
from app.infrastructure.fhir.mappers.professional_mapper import ProfessionalMapper
from app.models.gdpr_metadata import ProfessionalGdprMetadata
from app.schemas.professional import (
    AnonymizationStatus,
    ProfessionalDeletionContext,
    ProfessionalResponse,
    ProfessionalRestoreRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Helper functions for extracting data from FHIR Practitioner
# =============================================================================


def _extract_email_from_fhir(fhir_practitioner) -> str | None:
    """Extrait l'email d'une ressource FHIR Practitioner.

    Args:
        fhir_practitioner: Ressource FHIR Practitioner

    Returns:
        Email ou None si non trouvé
    """
    if not fhir_practitioner.telecom:
        return None
    for telecom in fhir_practitioner.telecom:
        if telecom.system == "email":
            return telecom.value
    return None


def _extract_keycloak_id_from_fhir(fhir_practitioner) -> str | None:
    """Extrait le keycloak_user_id d'une ressource FHIR Practitioner.

    Args:
        fhir_practitioner: Ressource FHIR Practitioner

    Returns:
        Keycloak user ID ou None si non trouvé
    """
    if not fhir_practitioner.identifier:
        return None
    for identifier in fhir_practitioner.identifier:
        if identifier.system == KEYCLOAK_SYSTEM:
            return identifier.value
    return None


# =============================================================================
# Admin endpoints
# =============================================================================


@router.post("/{professional_id}/investigation", response_model=ProfessionalResponse)
async def mark_professional_under_investigation(
    professional_id: int,
    context: ProfessionalDeletionContext,
    db: AsyncSession = Depends(get_session),
) -> ProfessionalResponse:
    """
    Marque un professionnel comme sous enquête médico-légale.

    Bloque toute tentative de suppression tant que l'enquête est active.

    Architecture hybride:
    - Métadonnées GDPR (under_investigation, investigation_notes): PostgreSQL
    - Données démographiques (pour la réponse): FHIR

    Args:
        professional_id: ID du professionnel
        context: Contexte avec notes d'enquête
        db: Session de base de données

    Returns:
        Professionnel mis à jour

    Raises:
        HTTPException 404: Professionnel non trouvé
    """
    # Récupérer métadonnées GDPR
    gdpr = await db.get(ProfessionalGdprMetadata, professional_id)
    if not gdpr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professional {professional_id} not found",
        )

    # Marquer sous enquête (local GDPR)
    gdpr.under_investigation = True
    gdpr.investigation_notes = context.reason or "Enquête médico-légale en cours"
    gdpr.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(gdpr)

    # Récupérer données FHIR pour la réponse
    fhir_client = get_fhir_client()
    fhir_practitioner = await fhir_client.read("Practitioner", gdpr.fhir_resource_id)

    # Publier événement
    await publish(
        "identity.professional.investigation_started",
        {
            "professional_id": gdpr.id,
            "keycloak_user_id": gdpr.keycloak_user_id,
            "investigation_notes": gdpr.investigation_notes,
            "marked_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Professionnel {professional_id} marqué sous enquête: {gdpr.investigation_notes}")

    return ProfessionalMapper.from_fhir(fhir_practitioner, gdpr.id, gdpr.to_dict())


@router.delete("/{professional_id}/investigation", response_model=ProfessionalResponse)
async def remove_investigation_status(
    professional_id: int,
    db: AsyncSession = Depends(get_session),
) -> ProfessionalResponse:
    """
    Retire le statut d'enquête d'un professionnel.

    Permet de nouveau la suppression du professionnel.

    Architecture hybride:
    - Métadonnées GDPR (under_investigation): PostgreSQL
    - Données démographiques (pour la réponse): FHIR

    Args:
        professional_id: ID du professionnel
        db: Session de base de données

    Returns:
        Professionnel mis à jour

    Raises:
        HTTPException 404: Professionnel non trouvé
    """
    # Récupérer métadonnées GDPR
    gdpr = await db.get(ProfessionalGdprMetadata, professional_id)
    if not gdpr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professional {professional_id} not found",
        )

    # Retirer enquête (local GDPR)
    gdpr.under_investigation = False
    gdpr.investigation_notes = None
    gdpr.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(gdpr)

    # Récupérer données FHIR pour la réponse
    fhir_client = get_fhir_client()
    fhir_practitioner = await fhir_client.read("Practitioner", gdpr.fhir_resource_id)

    # Publier événement
    await publish(
        "identity.professional.investigation_cleared",
        {
            "professional_id": gdpr.id,
            "keycloak_user_id": gdpr.keycloak_user_id,
            "cleared_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Professionnel {professional_id} enquête retirée")

    return ProfessionalMapper.from_fhir(fhir_practitioner, gdpr.id, gdpr.to_dict())


@router.post("/{professional_id}/restore", response_model=ProfessionalResponse)
async def restore_soft_deleted_professional(
    professional_id: int,
    restore_request: ProfessionalRestoreRequest,
    db: AsyncSession = Depends(get_session),
) -> ProfessionalResponse:
    """
    Restaure un professionnel soft deleted (pendant période de grâce).

    Impossible de restaurer si déjà anonymisé.

    Architecture hybride:
    - Métadonnées GDPR (soft_deleted_at, anonymized_at): PostgreSQL
    - Données démographiques + active status: FHIR

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
    # Récupérer métadonnées GDPR
    gdpr = await db.get(ProfessionalGdprMetadata, professional_id)
    if not gdpr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Professional {professional_id} not found",
        )

    # Vérifier si anonymisé
    if gdpr.anonymized_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot restore professional {professional_id}: "
                "already anonymized. Anonymization is irreversible."
            ),
        )

    # Restaurer métadonnées locales
    gdpr.soft_deleted_at = None
    gdpr.deletion_reason = None
    gdpr.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(gdpr)

    # Restaurer dans FHIR (active = true)
    fhir_client = get_fhir_client()
    fhir_practitioner = await fhir_client.read("Practitioner", gdpr.fhir_resource_id)
    fhir_practitioner.active = True
    await fhir_client.update(fhir_practitioner)

    # Publier événement
    await publish(
        "identity.professional.restored",
        {
            "professional_keycloak_id": gdpr.keycloak_user_id,
            "restore_reason": restore_request.restore_reason,
            "restored_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Professionnel {professional_id} restauré: {restore_request.restore_reason}")

    return ProfessionalMapper.from_fhir(fhir_practitioner, gdpr.id, gdpr.to_dict())


@router.get("/deleted", response_model=list[AnonymizationStatus])
async def list_soft_deleted_professionals(
    db: AsyncSession = Depends(get_session),
) -> list[AnonymizationStatus]:
    """
    Liste tous les professionnels soft deleted en attente d'anonymisation.

    Retourne uniquement ceux dans la période de grâce (pas encore anonymisés).

    Architecture hybride:
    - Query sur GDPR metadata (soft_deleted_at, anonymized_at)
    - Fetch FHIR pour email de chaque professionnel

    Note: Pattern N+1 acceptable pour endpoint admin (faible volume).

    Args:
        db: Session de base de données

    Returns:
        Liste des professionnels soft deleted avec statut anonymisation
    """
    # Récupérer soft deleted (pas anonymisés)
    result = await db.execute(
        select(ProfessionalGdprMetadata).where(
            ProfessionalGdprMetadata.soft_deleted_at.isnot(None),
            ProfessionalGdprMetadata.anonymized_at.is_(None),
        )
    )
    gdpr_records = result.scalars().all()

    # Récupérer client FHIR
    fhir_client = get_fhir_client()

    # Convertir en AnonymizationStatus (avec fetch FHIR pour email)
    statuses = []
    for gdpr in gdpr_records:
        # Récupérer email depuis FHIR
        email = None
        try:
            fhir_practitioner = await fhir_client.read("Practitioner", gdpr.fhir_resource_id)
            email = _extract_email_from_fhir(fhir_practitioner)
        except Exception as e:
            logger.warning(
                f"Impossible de récupérer FHIR Practitioner {gdpr.fhir_resource_id}: {e}"
            )

        status_obj = AnonymizationStatus(
            professional_id=gdpr.id,
            keycloak_user_id=gdpr.keycloak_user_id,
            email=email,
            soft_deleted_at=gdpr.soft_deleted_at,
            anonymized_at=gdpr.anonymized_at,
            deletion_reason=gdpr.deletion_reason,
        )
        statuses.append(status_obj)

    logger.info(f"Listage {len(statuses)} professionnels soft deleted")

    return statuses
