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


__all__ = [
    "AfriCareException",
    "AnonymizationError",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "KeycloakServiceError",
    "NotFoundError",
    "ProblemDetail",
    "RFC9457Exception",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationError",
]
