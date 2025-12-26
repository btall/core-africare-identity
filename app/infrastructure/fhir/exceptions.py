"""FHIR-specific exceptions for error handling."""

from typing import Any


class FHIRError(Exception):
    """Base exception for FHIR operations."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class FHIRConnectionError(FHIRError):
    """Raised when connection to FHIR server fails."""

    pass


class FHIRResourceNotFoundError(FHIRError):
    """Raised when a FHIR resource is not found (404)."""

    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            f"{resource_type}/{resource_id} not found",
            {"resource_type": resource_type, "resource_id": resource_id},
        )
        self.resource_type = resource_type
        self.resource_id = resource_id


class FHIRValidationError(FHIRError):
    """Raised when FHIR resource validation fails."""

    def __init__(self, message: str, issues: list[dict[str, Any]] | None = None):
        super().__init__(message, {"issues": issues or []})
        self.issues = issues or []


class FHIROperationError(FHIRError):
    """Raised when a FHIR operation fails (non-2xx response)."""

    def __init__(self, status_code: int, message: str, operation_outcome: dict | None = None):
        super().__init__(message, {"status_code": status_code, "outcome": operation_outcome})
        self.status_code = status_code
        self.operation_outcome = operation_outcome
