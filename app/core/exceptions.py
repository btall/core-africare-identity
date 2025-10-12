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

__all__ = [
    "AfriCareException",
    "ConflictError",
    "ForbiddenError",
    "InternalServerError",
    "NotFoundError",
    "ProblemDetail",
    "RFC9457Exception",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationError",
]
