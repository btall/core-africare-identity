"""Schemas Pydantic pour validation des donnees."""

from app.schemas.keycloak import (
    KeycloakUser,
    KeycloakUserAttributes,
    KeycloakWebhookEvent,
    SyncResult,
    WebhookHealthCheck,
    WebhookSignature,
    WebhookVerificationResponse,
)
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
    "COMMON_RESPONSES",
    "ConflictErrorResponse",
    "KeycloakUser",
    "KeycloakUserAttributes",
    "KeycloakWebhookEvent",
    "ProblemDetailResponse",
    "SyncResult",
    "ValidationErrorResponse",
    "WebhookHealthCheck",
    "WebhookSignature",
    "WebhookVerificationResponse",
    "admin_responses",
    "auth_responses",
    "build_responses",
    "create_responses",
    "delete_responses",
    "list_responses",
    "read_responses",
    "update_responses",
]
