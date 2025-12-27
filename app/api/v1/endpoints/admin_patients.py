"""Endpoints administrateur pour gestion avancée des patients.

Ce module fournit des endpoints réservés aux administrateurs pour:
- Marquer/retirer statut d'enquête (blocage suppression)
- Restaurer patients soft deleted (pendant période de grâce)
- Lister patients en attente d'anonymisation

Architecture hybride FHIR + PostgreSQL:
- PatientGdprMetadata: métadonnées GDPR locales (enquête, soft delete, anonymisation)
- HAPI FHIR: données démographiques (email, nom, etc.)
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.events import publish
from app.core.exceptions import PatientDeletionBlockedError
from app.infrastructure.fhir.client import get_fhir_client
from app.infrastructure.fhir.mappers.patient_mapper import PatientMapper
from app.models.gdpr_metadata import PatientGdprMetadata
from app.schemas.patient import (
    PatientAnonymizationStatus,
    PatientDeletionContext,
    PatientDeletionRequest,
    PatientResponse,
    PatientRestoreRequest,
)
from app.services.keycloak_sync_service import (
    _generate_patient_correlation_hash,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_email_from_fhir(fhir_patient) -> str | None:
    """Extrait l'email depuis une ressource FHIR Patient."""
    if not fhir_patient.telecom:
        return None
    for telecom in fhir_patient.telecom:
        if telecom.system == "email":
            return telecom.value
    return None


def _extract_national_id_from_fhir(fhir_patient) -> str | None:
    """Extrait le national_id depuis une ressource FHIR Patient."""
    from app.infrastructure.fhir.identifiers import NATIONAL_ID_SYSTEM

    if not fhir_patient.identifier:
        return None
    for identifier in fhir_patient.identifier:
        if identifier.system == NATIONAL_ID_SYSTEM:
            return identifier.value
    return None


@router.post("/{patient_id}/investigation", response_model=PatientResponse)
async def mark_patient_under_investigation(
    patient_id: int,
    context: PatientDeletionContext,
    db: AsyncSession = Depends(get_session),
) -> PatientResponse:
    """
    Marque un patient comme sous enquête.

    Bloque toute tentative de suppression tant que l'enquête est active.

    Args:
        patient_id: ID du patient
        context: Contexte avec notes d'enquête
        db: Session de base de données

    Returns:
        Patient mis à jour

    Raises:
        HTTPException 404: Patient non trouvé
    """
    fhir_client = get_fhir_client()

    # Récupérer métadonnées GDPR
    gdpr = await db.get(PatientGdprMetadata, patient_id)
    if not gdpr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )

    # Marquer sous enquête (opération locale uniquement)
    gdpr.under_investigation = True
    gdpr.investigation_notes = context.reason or "Enquête en cours"
    gdpr.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(gdpr)

    # Publier événement
    await publish(
        "identity.patient.investigation_started",
        {
            "patient_id": gdpr.id,
            "keycloak_user_id": gdpr.keycloak_user_id,
            "investigation_notes": gdpr.investigation_notes,
            "marked_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Patient {patient_id} marqué sous enquête: {gdpr.investigation_notes}")

    # Récupérer données FHIR pour réponse complète
    fhir_patient = await fhir_client.read("Patient", gdpr.fhir_resource_id)
    if not fhir_patient:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Patient FHIR resource {gdpr.fhir_resource_id} not found",
        )

    return PatientMapper.from_fhir(fhir_patient, gdpr.id, gdpr.to_dict())


@router.delete("/{patient_id}/investigation", response_model=PatientResponse)
async def remove_investigation_status(
    patient_id: int,
    db: AsyncSession = Depends(get_session),
) -> PatientResponse:
    """
    Retire le statut d'enquête d'un patient.

    Permet de nouveau la suppression du patient.

    Args:
        patient_id: ID du patient
        db: Session de base de données

    Returns:
        Patient mis à jour

    Raises:
        HTTPException 404: Patient non trouvé
    """
    fhir_client = get_fhir_client()

    # Récupérer métadonnées GDPR
    gdpr = await db.get(PatientGdprMetadata, patient_id)
    if not gdpr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )

    # Retirer enquête (opération locale uniquement)
    gdpr.under_investigation = False
    gdpr.investigation_notes = None
    gdpr.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(gdpr)

    # Publier événement
    await publish(
        "identity.patient.investigation_cleared",
        {
            "patient_id": gdpr.id,
            "keycloak_user_id": gdpr.keycloak_user_id,
            "cleared_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Patient {patient_id} enquête retirée")

    # Récupérer données FHIR pour réponse complète
    fhir_patient = await fhir_client.read("Patient", gdpr.fhir_resource_id)
    if not fhir_patient:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Patient FHIR resource {gdpr.fhir_resource_id} not found",
        )

    return PatientMapper.from_fhir(fhir_patient, gdpr.id, gdpr.to_dict())


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient_admin(
    patient_id: int,
    db: AsyncSession = Depends(get_session),
    deletion_request: PatientDeletionRequest = Body(
        default=PatientDeletionRequest(
            deletion_reason="admin_action",
            investigation_check_override=False,
        ),
        description="Paramètres de suppression (optionnel, défaut: admin_action)",
    ),
) -> None:
    """
    Supprime un patient avec le système RGPD (soft delete + période de grâce 7 jours).

    Body JSON optionnel :
    - Si omis : utilise deletion_reason="admin_action" par défaut
    - Si fourni : utilise deletion_reason, investigation_check_override, notes

    Cette méthode déclenche:
    1. Soft delete avec remplissage de soft_deleted_at
    2. Génération du correlation_hash pour détection retour utilisateur
    3. Démarrage période de grâce de 7 jours
    4. Désactivation ressource FHIR (active=false)
    5. Publication événement identity.patient.soft_deleted
    6. Anonymisation automatique après 7 jours (via scheduler)

    Args:
        patient_id: ID du patient à supprimer
        db: Session de base de données
        deletion_request: Paramètres de suppression (optionnel, défaut admin_action)

    Returns:
        None (204 No Content)

    Raises:
        HTTPException 404: Patient non trouvé
        HTTPException 423: Patient sous enquête (si investigation_check_override=False)

    Examples:
        DELETE /api/v1/admin/patients/123
        (sans body, utilise deletion_reason="admin_action")

        DELETE /api/v1/admin/patients/123
        Body: {"deletion_reason": "user_request", "notes": "Demande du patient"}
    """
    fhir_client = get_fhir_client()

    # Récupérer métadonnées GDPR
    gdpr = await db.get(PatientGdprMetadata, patient_id)
    if not gdpr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )

    # Vérifier si déjà soft deleted
    if gdpr.soft_deleted_at:
        logger.warning(f"Patient {patient_id} déjà soft deleted")
        return  # Idempotent

    # Vérifier si sous enquête (sauf si override)
    if gdpr.under_investigation and not deletion_request.investigation_check_override:
        raise PatientDeletionBlockedError(
            patient_id=patient_id,
            keycloak_user_id=gdpr.keycloak_user_id,
            investigation_notes=gdpr.investigation_notes,
        )

    # Récupérer données FHIR pour email (nécessaire pour correlation_hash)
    fhir_patient = await fhir_client.read("Patient", gdpr.fhir_resource_id)
    if not fhir_patient:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Patient FHIR resource {gdpr.fhir_resource_id} not found",
        )

    # Extraire email et national_id depuis FHIR
    email = _extract_email_from_fhir(fhir_patient)
    national_id = _extract_national_id_from_fhir(fhir_patient)

    # Générer correlation_hash AVANT soft delete (pour détection retour utilisateur)
    if not gdpr.correlation_hash and email:
        gdpr.correlation_hash = _generate_patient_correlation_hash(
            email=email,
            national_id=national_id,
        )

    # Marquer comme soft deleted (métadonnées GDPR locales)
    gdpr.soft_deleted_at = datetime.now(UTC)
    gdpr.deletion_reason = deletion_request.deletion_reason
    gdpr.updated_at = datetime.now(UTC)

    # Désactiver dans FHIR
    fhir_patient.active = False
    await fhir_client.update(fhir_patient)

    await db.commit()

    # Publier événement
    await publish(
        "identity.patient.soft_deleted",
        {
            "patient_id": gdpr.id,
            "keycloak_user_id": gdpr.keycloak_user_id,
            "fhir_resource_id": gdpr.fhir_resource_id,
            "deletion_reason": deletion_request.deletion_reason,
            "soft_deleted_at": gdpr.soft_deleted_at.isoformat(),
            "grace_period_days": 7,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Patient {patient_id} soft deleted (raison: {deletion_request.deletion_reason})")


@router.post("/{patient_id}/restore", response_model=PatientResponse)
async def restore_soft_deleted_patient(
    patient_id: int,
    restore_request: PatientRestoreRequest,
    db: AsyncSession = Depends(get_session),
) -> PatientResponse:
    """
    Restaure un patient soft deleted (pendant période de grâce).

    Impossible de restaurer si déjà anonymisé.

    Args:
        patient_id: ID du patient
        restore_request: Raison de la restauration
        db: Session de base de données

    Returns:
        Patient restauré

    Raises:
        HTTPException 404: Patient non trouvé
        HTTPException 422: Déjà anonymisé (impossible de restaurer)
    """
    fhir_client = get_fhir_client()

    # Récupérer métadonnées GDPR
    gdpr = await db.get(PatientGdprMetadata, patient_id)
    if not gdpr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )

    # Vérifier si anonymisé
    if gdpr.anonymized_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot restore patient {patient_id}: "
                "already anonymized. Anonymization is irreversible."
            ),
        )

    # Récupérer ressource FHIR
    fhir_patient = await fhir_client.read("Patient", gdpr.fhir_resource_id)
    if not fhir_patient:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Patient FHIR resource {gdpr.fhir_resource_id} not found",
        )

    # Restaurer métadonnées GDPR locales
    gdpr.soft_deleted_at = None
    gdpr.deletion_reason = None
    gdpr.updated_at = datetime.now(UTC)

    # Réactiver dans FHIR
    fhir_patient.active = True
    await fhir_client.update(fhir_patient)

    await db.commit()
    await db.refresh(gdpr)

    # Publier événement
    await publish(
        "identity.patient.restored",
        {
            "patient_id": gdpr.id,
            "keycloak_user_id": gdpr.keycloak_user_id,
            "fhir_resource_id": gdpr.fhir_resource_id,
            "restore_reason": restore_request.restore_reason,
            "restored_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Patient {patient_id} restauré: {restore_request.restore_reason}")

    return PatientMapper.from_fhir(fhir_patient, gdpr.id, gdpr.to_dict())


@router.get("/deleted", response_model=list[PatientAnonymizationStatus])
async def list_soft_deleted_patients(
    db: AsyncSession = Depends(get_session),
) -> list[PatientAnonymizationStatus]:
    """
    Liste tous les patients soft deleted en attente d'anonymisation.

    Retourne uniquement ceux dans la période de grâce (pas encore anonymisés).

    Args:
        db: Session de base de données

    Returns:
        Liste des patients soft deleted avec statut anonymisation
    """
    fhir_client = get_fhir_client()

    # Récupérer métadonnées GDPR soft deleted (pas encore anonymisés)
    result = await db.execute(
        select(PatientGdprMetadata).where(
            PatientGdprMetadata.soft_deleted_at.isnot(None),
            PatientGdprMetadata.anonymized_at.is_(None),
        )
    )
    gdpr_records = result.scalars().all()

    # Convertir en PatientAnonymizationStatus (avec fetch FHIR pour email)
    statuses = []
    for gdpr in gdpr_records:
        # Récupérer email depuis FHIR (peut être None si ressource non trouvée)
        email = None
        try:
            fhir_patient = await fhir_client.read("Patient", gdpr.fhir_resource_id)
            if fhir_patient:
                email = _extract_email_from_fhir(fhir_patient)
        except Exception:
            # Si FHIR non disponible, continuer sans email
            logger.warning(f"Cannot fetch FHIR patient {gdpr.fhir_resource_id}")

        status_obj = PatientAnonymizationStatus(
            patient_id=gdpr.id,
            keycloak_user_id=gdpr.keycloak_user_id,
            email=email,
            soft_deleted_at=gdpr.soft_deleted_at,
            anonymized_at=gdpr.anonymized_at,
            deletion_reason=gdpr.deletion_reason,
        )
        statuses.append(status_obj)

    logger.info(f"Listage {len(statuses)} patients soft deleted")

    return statuses
