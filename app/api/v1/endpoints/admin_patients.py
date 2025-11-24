"""Endpoints administrateur pour gestion avancée des patients.

Ce module fournit des endpoints réservés aux administrateurs pour:
- Marquer/retirer statut d'enquête (blocage suppression)
- Restaurer patients soft deleted (pendant période de grâce)
- Lister patients en attente d'anonymisation
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.events import publish
from app.core.exceptions import PatientDeletionBlockedError
from app.models.patient import Patient
from app.schemas.patient import (
    PatientAnonymizationStatus,
    PatientDeletionContext,
    PatientDeletionRequest,
    PatientResponse,
    PatientRestoreRequest,
)
from app.services.keycloak_sync_service import (
    _generate_patient_correlation_hash,
    _soft_delete,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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
    # Récupérer patient
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )

    # Marquer sous enquête
    patient.under_investigation = True
    patient.investigation_notes = context.reason or "Enquête en cours"
    patient.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(patient)

    # Publier événement
    await publish(
        "identity.patient.investigation_started",
        {
            "patient_id": patient.id,
            "keycloak_user_id": patient.keycloak_user_id,
            "investigation_notes": patient.investigation_notes,
            "marked_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Patient {patient_id} marqué sous enquête: {patient.investigation_notes}")

    return PatientResponse.model_validate(patient)


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
    # Récupérer patient
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )

    # Retirer enquête
    patient.under_investigation = False
    patient.investigation_notes = None
    patient.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(patient)

    # Publier événement
    await publish(
        "identity.patient.investigation_cleared",
        {
            "patient_id": patient.id,
            "keycloak_user_id": patient.keycloak_user_id,
            "cleared_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Patient {patient_id} enquête retirée")

    return PatientResponse.model_validate(patient)


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient_admin(
    patient_id: int,
    deletion_request: PatientDeletionRequest,
    db: AsyncSession = Depends(get_session),
) -> None:
    """
    Supprime un patient avec le système RGPD (soft delete + période de grâce 7 jours).

    Cette méthode déclenche:
    1. Soft delete avec remplissage de soft_deleted_at
    2. Génération du correlation_hash pour détection retour utilisateur
    3. Démarrage période de grâce de 7 jours
    4. Publication événement identity.patient.soft_deleted
    5. Anonymisation automatique après 7 jours (via scheduler)

    Args:
        patient_id: ID du patient à supprimer
        deletion_request: Raison et paramètres de suppression
        db: Session de base de données

    Returns:
        None (204 No Content)

    Raises:
        HTTPException 404: Patient non trouvé
        HTTPException 423: Patient sous enquête (deletion_request.investigation_check_override=False)
    """
    # Récupérer patient
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )

    # Vérifier si déjà soft deleted
    if patient.soft_deleted_at:
        logger.warning(f"Patient {patient_id} déjà soft deleted")
        return  # Idempotent

    try:
        # Générer correlation_hash AVANT soft delete
        if not patient.correlation_hash and patient.email:
            patient.correlation_hash = _generate_patient_correlation_hash(
                email=patient.email,
                national_id=patient.national_id,
            )

        # Stocker deletion_reason
        patient.deletion_reason = deletion_request.deletion_reason

        # Créer un événement fictif pour _soft_delete (utilise même interface que webhook)
        class MockEvent:
            def __init__(self, reason, override):
                self.user_id = patient.keycloak_user_id
                self.deletion_reason = reason
                self.investigation_check_override = override

        mock_event = MockEvent(
            deletion_request.deletion_reason,
            deletion_request.investigation_check_override,
        )

        # Appeler _soft_delete (gère under_investigation check, soft_deleted_at, événement)
        await _soft_delete(patient, mock_event)

        await db.commit()

        logger.info(
            f"Patient {patient_id} soft deleted (raison: {deletion_request.deletion_reason})"
        )

    except PatientDeletionBlockedError:
        # Re-raise l'exception RFC 9457 telle quelle
        raise


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
    # Récupérer patient
    patient = await db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient {patient_id} not found",
        )

    # Vérifier si anonymisé
    if patient.anonymized_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot restore patient {patient_id}: "
                "already anonymized. Anonymization is irreversible."
            ),
        )

    # Restaurer
    patient.is_active = True
    patient.soft_deleted_at = None
    patient.deletion_reason = None
    patient.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(patient)

    # Publier événement
    await publish(
        "identity.patient.restored",
        {
            "patient_id": patient.id,
            "keycloak_user_id": patient.keycloak_user_id,
            "restore_reason": restore_request.restore_reason,
            "restored_at": datetime.now(UTC).isoformat(),
        },
    )

    logger.info(f"Patient {patient_id} restauré: {restore_request.restore_reason}")

    return PatientResponse.model_validate(patient)


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
    # Récupérer soft deleted (pas anonymisés)
    result = await db.execute(
        select(Patient).where(
            Patient.soft_deleted_at.isnot(None),
            Patient.anonymized_at.is_(None),
        )
    )
    patients = result.scalars().all()

    # Convertir en PatientAnonymizationStatus
    statuses = []
    for patient in patients:
        status_obj = PatientAnonymizationStatus(
            patient_id=patient.id,
            keycloak_user_id=patient.keycloak_user_id,
            email=patient.email,
            soft_deleted_at=patient.soft_deleted_at,
            anonymized_at=patient.anonymized_at,
            deletion_reason=patient.deletion_reason,
        )
        statuses.append(status_obj)

    logger.info(f"Listage {len(statuses)} patients soft deleted")

    return statuses
