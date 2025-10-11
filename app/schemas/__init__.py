"""Schemas Pydantic pour validation des donnees."""

from app.schemas.responses import (
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
    # Schémas de réponse
    "ProblemDetailResponse",
    "ValidationErrorResponse",
    "ConflictErrorResponse",
    # Dictionnaire complet (legacy - utiliser les helpers granulaires)
    "COMMON_RESPONSES",
    # Helpers granulaires (recommandés)
    "build_responses",
    "auth_responses",
    "read_responses",
    "list_responses",
    "create_responses",
    "update_responses",
    "delete_responses",
    "admin_responses",
]
