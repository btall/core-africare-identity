import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from keycloak import KeycloakOpenID
from opentelemetry import trace
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from pydantic import BaseModel

from app.core.config import settings

LoggingInstrumentor().instrument(set_logging_format=True)
logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Keycloak client configuration
keycloak_openid = KeycloakOpenID(
    server_url=settings.KEYCLOAK_SERVER_URL,
    client_id=settings.KEYCLOAK_CLIENT_ID,
    realm_name=settings.KEYCLOAK_REALM,
    client_secret_key=settings.KEYCLOAK_CLIENT_SECRET,
)

# Security scheme for Bearer token
security_scheme = HTTPBearer()


class User(BaseModel):
    sub: str  # Keycloak user ID
    email: str | None = None
    preferred_username: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    realm_access: dict | None = None
    resource_access: dict | None = None


async def verify_token(token: str) -> dict:
    """Verify JWT token with Keycloak."""
    with tracer.start_as_current_span("verify_keycloak_token") as span:
        try:
            # Decode and verify token with Keycloak
            token_info = keycloak_openid.decode_token(token)
            span.set_attribute("auth.user_id", token_info.get("sub"))
            return token_info
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            span.set_attribute("auth.error", True)
            span.set_attribute("auth.error_detail", str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e


async def get_token_data(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
) -> dict:
    """Extract and verify token from HTTP Bearer credentials."""
    return await verify_token(credentials.credentials)


async def get_current_user(token_data: Annotated[dict, Depends(get_token_data)]) -> dict:
    """
    Get current user from verified Keycloak token.

    Returns raw token data dict for convenience in endpoints.
    For structured User model, use get_current_user_model().
    """
    with tracer.start_as_current_span("get_current_user") as span:
        span.set_attribute("auth.user_id", token_data.get("sub"))
        span.set_attribute("auth.username", token_data.get("preferred_username", "unknown"))
        logger.info(f"User authenticated: {token_data.get('sub')}")
        return token_data


async def get_current_user_model(token_data: Annotated[dict, Depends(get_token_data)]) -> User:
    """Get current user as Pydantic User model from verified Keycloak token."""
    with tracer.start_as_current_span("get_current_user_model") as span:
        try:
            user = User(**token_data)
            span.set_attribute("auth.user_id", user.sub)
            span.set_attribute("auth.username", user.preferred_username or "unknown")
            logger.info(f"User authenticated: {user.sub}")
            return user
        except Exception as e:
            logger.error(f"Failed to create user from token data: {e}")
            span.set_attribute("auth.error", True)
            span.set_attribute("auth.error_detail", str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            ) from e


def check_user_role(user: User, required_role: str) -> bool:
    """Check if user has required role in realm_access or resource_access."""
    # Check realm roles
    if user.realm_access and "roles" in user.realm_access:
        if required_role in user.realm_access["roles"]:
            return True

    # Check client-specific roles
    if user.resource_access and settings.KEYCLOAK_CLIENT_ID in user.resource_access:
        client_roles = user.resource_access[settings.KEYCLOAK_CLIENT_ID].get("roles", [])
        if required_role in client_roles:
            return True

    return False


def require_roles(*roles: str, require_all: bool = False):
    """
    Dependency factory for role-based access control.

    Args:
        *roles: One or more role names required for access
        require_all: If True, user must have ALL roles. If False (default), user needs ANY role.

    Returns:
        FastAPI dependency function that validates user roles

    Examples:
        # Require at least one of the specified roles (OR logic)
        @router.get("/data", dependencies=[Depends(require_roles("patient", "professional"))])

        # Require all specified roles (AND logic)
        @router.get("/admin", dependencies=[Depends(require_roles("admin", "manager", require_all=True))])

        # Single role check
        @router.get("/patient-only", dependencies=[Depends(require_roles("patient"))])
    """

    async def role_checker(current_user: User = Depends(get_current_user_model)) -> User:
        with tracer.start_as_current_span("check_user_roles") as span:
            span.set_attribute("auth.required_roles", ",".join(roles))
            span.set_attribute("auth.require_all", require_all)
            span.set_attribute("auth.user_id", current_user.sub)

            user_roles = []

            # Collect all user roles from realm and client
            if current_user.realm_access and "roles" in current_user.realm_access:
                user_roles.extend(current_user.realm_access["roles"])

            if (
                current_user.resource_access
                and settings.KEYCLOAK_CLIENT_ID in current_user.resource_access
            ):
                client_roles = current_user.resource_access[settings.KEYCLOAK_CLIENT_ID].get(
                    "roles", []
                )
                user_roles.extend(client_roles)

            span.set_attribute("auth.user_roles", ",".join(user_roles))

            # Check role requirements
            if require_all:
                # User must have ALL required roles (AND logic)
                has_access = all(role in user_roles for role in roles)
                missing_roles = [role for role in roles if role not in user_roles]
            else:
                # User must have AT LEAST ONE required role (OR logic)
                has_access = any(role in user_roles for role in roles)
                missing_roles = list(roles) if not has_access else []

            if not has_access:
                logger.warning(
                    f"Access denied for user {current_user.sub}. "
                    f"Required roles: {roles} (require_all={require_all}). "
                    f"User roles: {user_roles}. "
                    f"Missing: {missing_roles}"
                )
                span.set_attribute("auth.access_denied", True)
                span.set_attribute("auth.missing_roles", ",".join(missing_roles))

                detail = (
                    f"Access denied. Required roles: {', '.join(roles)}"
                    if not require_all
                    else f"Access denied. All required roles must be present: {', '.join(roles)}"
                )

                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=detail,
                )

            span.set_attribute("auth.access_granted", True)
            logger.info(f"Access granted for user {current_user.sub} with roles: {user_roles}")
            return current_user

    return role_checker


# Convenience dependencies for common role checks (backward compatibility)
async def get_current_patient(current_user: User = Depends(require_roles("patient"))) -> User:
    """Get current user with patient role validation."""
    return current_user


async def get_current_professional(
    current_user: User = Depends(require_roles("professional")),
) -> User:
    """Get current user with professional role validation."""
    return current_user
