"""
RFC 9457 Problem Details pour HTTP APIs - Exceptions AfriCare.

Ce module réexporte les exceptions du module fastapi-errors-rfc9457.
Les anciens noms (AfriCareException) sont conservés pour la rétrocompatibilité.
"""

from fastapi_errors_rfc9457 import (
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    ProblemDetail,
    RFC9457Exception,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)

# Alias pour rétrocompatibilité
AfriCareException = RFC9457Exception


class KeycloakServiceError(ServiceUnavailableError):
    """
    Exception levée lorsque le service Keycloak est indisponible ou renvoie une erreur.

    Cette exception est utilisée pour gérer les erreurs de communication avec Keycloak
    (récupération des rôles, validation des tokens, etc.) en respectant RFC 9457.

    Attributes:
        status_code: Code HTTP 503 (Service Unavailable)
        problem_detail: Détails de l'erreur au format RFC 9457

    Example:
        ```python
        try:
            roles = await get_user_roles_from_keycloak(user_id)
        except Exception as e:
            raise KeycloakServiceError(
                detail=f"Cannot retrieve roles for user {user_id}",
                instance="/api/v1/webhooks"
            ) from e
        ```
    """

    def __init__(
        self,
        detail: str = "Keycloak service is unavailable",
        instance: str | None = None,
        retry_after: int | None = None,
    ):
        """
        Initialise une exception Keycloak avec détails RFC 9457.

        Args:
            detail: Description détaillée de l'erreur
            instance: URI identifiant l'occurrence spécifique de l'erreur
            retry_after: Nombre de secondes avant de réessayer (optionnel)
        """
        super().__init__(
            detail=detail,
            retry_after=retry_after,
            instance=instance,
        )


class AnonymizationError(InternalServerError):
    """
    Exception levée lors d'un échec d'anonymisation de données RGPD.

    Cette exception est utilisée lorsque le processus d'anonymisation (hashing,
    chiffrement, suppression) échoue pour des données patient ou professional.

    Attributes:
        status_code: Code HTTP 500 (Internal Server Error)
        problem_detail: Détails de l'erreur au format RFC 9457

    Example:
        ```python
        try:
            anonymized_data = await anonymize_patient(patient_id)
        except Exception as e:
            raise AnonymizationError(
                detail="Failed to encrypt patient sensitive data",
                instance=f"/api/v1/patients/{patient_id}/anonymize"
            ) from e
        ```
    """

    def __init__(
        self,
        detail: str = "Data anonymization failed",
        instance: str | None = None,
    ):
        """
        Initialise une exception d'anonymisation avec détails RFC 9457.

        Args:
            detail: Description détaillée de l'erreur d'anonymisation
            instance: URI identifiant l'occurrence spécifique de l'erreur
        """
        super().__init__(
            detail=detail,
            instance=instance,
        )


class ProfessionalDeletionBlockedError(RFC9457Exception):
    """
    Exception levée lorsqu'une suppression de professionnel est bloquée.

    Cette exception est utilisée lorsqu'un professionnel ne peut pas être supprimé
    car il est sous enquête médico-légale (under_investigation=True) ou pour
    d'autres raisons légales/administratives.

    Attributes:
        status_code: Code HTTP 423 (Locked)
        problem_detail: Détails de l'erreur au format RFC 9457

    Example:
        ```python
        if professional.under_investigation:
            raise ProfessionalDeletionBlockedError(
                professional_id=professional.id,
                reason="under_investigation",
                investigation_notes=professional.investigation_notes
            )
        ```
    """

    def __init__(
        self,
        professional_id: int,
        reason: str = "under_investigation",
        investigation_notes: str | None = None,
    ):
        """
        Initialise une exception de blocage de suppression avec détails RFC 9457.

        Args:
            professional_id: ID du professionnel concerné
            reason: Raison du blocage (under_investigation, legal_hold, etc.)
            investigation_notes: Notes explicatives sur le blocage
        """
        detail_parts = [f"Cannot delete professional {professional_id}: {reason}"]
        if investigation_notes:
            detail_parts.append(f"Notes: {investigation_notes}")

        super().__init__(
            status_code=423,  # Locked
            title="Professional Deletion Blocked",
            detail=". ".join(detail_parts),
            type="https://africare.app/errors/deletion-blocked",
            instance=f"/api/v1/professionals/{professional_id}",
        )


class PatientDeletionBlockedError(RFC9457Exception):
    """
    Exception levée lorsqu'une suppression de patient est bloquée.

    Cette exception est utilisée lorsqu'un patient ne peut pas être supprimé
    car il est sous enquête (under_investigation=True) ou pour d'autres
    raisons légales/administratives.

    Attributes:
        status_code: Code HTTP 423 (Locked)
        problem_detail: Détails de l'erreur au format RFC 9457

    Example:
        ```python
        if patient.under_investigation:
            raise PatientDeletionBlockedError(
                patient_id=patient.id,
                reason="under_investigation",
                investigation_notes=patient.investigation_notes
            )
        ```
    """

    def __init__(
        self,
        patient_id: int,
        reason: str = "under_investigation",
        investigation_notes: str | None = None,
    ):
        """
        Initialise une exception de blocage de suppression avec détails RFC 9457.

        Args:
            patient_id: ID du patient concerné
            reason: Raison du blocage (under_investigation, legal_hold, etc.)
            investigation_notes: Notes explicatives sur le blocage
        """
        detail_parts = [f"Cannot delete patient {patient_id}: {reason}"]
        if investigation_notes:
            detail_parts.append(f"Notes: {investigation_notes}")

        super().__init__(
            status_code=423,  # Locked
            title="Patient Deletion Blocked",
            detail=". ".join(detail_parts),
            type="https://africare.app/errors/deletion-blocked",
            instance=f"/api/v1/patients/{patient_id}",
        )


__all__ = [
    "AfriCareException",
    "AnonymizationError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "KeycloakServiceError",
    "NotFoundError",
    "PatientDeletionBlockedError",
    "ProblemDetail",
    "ProfessionalDeletionBlockedError",
    "RFC9457Exception",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationError",
]
