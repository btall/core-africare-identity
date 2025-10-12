"""
Schémas de réponses OpenAPI pour RFC 9457 Problem Details.

Ce module réexporte les schémas du module fastapi-errors-rfc9457.
"""

from fastapi_errors_rfc9457 import (
    COMMON_RESPONSES,
    ConflictErrorResponse,
    ProblemDetailResponse,
    ValidationErrorResponse,
    admin_responses,
    auth_responses,
    build_responses,
    create_responses,
    delete_responses,
    list_responses,
    read_responses,
    update_responses,
)

__all__ = [
    "COMMON_RESPONSES",
    "ConflictErrorResponse",
    "ProblemDetailResponse",
    "ValidationErrorResponse",
    "admin_responses",
    "auth_responses",
    "build_responses",
    "create_responses",
    "delete_responses",
    "list_responses",
    "read_responses",
    "update_responses",
]
