import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from keycloak import KeycloakOpenID
from opentelemetry import trace
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Keycloak client configuration (bearer-only mode - no client_secret needed)
keycloak_openid = KeycloakOpenID(
    server_url=settings.KEYCLOAK_SERVER_URL,
    client_id=settings.KEYCLOAK_CLIENT_ID,
    realm_name=settings.KEYCLOAK_REALM,
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

    @property
    def is_admin(self) -> bool:
        """Check si l'utilisateur a un rôle admin quelconque."""
        if self.realm_access and "roles" in self.realm_access:
            return any(role.startswith("admin") for role in self.realm_access["roles"])
        return False

    def is_owner(self, resource_owner_id: str) -> bool:
        """Check si l'utilisateur est le propriétaire de la ressource."""
        return self.sub == resource_owner_id

    def verify_access(self, resource_owner_id: str) -> str:
        """
        Vérifie l'accès et retourne la raison pour traçabilité RGPD.

        Returns:
            "owner" si propriétaire de la ressource
            "admin_supervision" si admin (pas owner)

        Raises:
            HTTPException 403 si ni owner ni admin
        """
        if self.is_owner(resource_owner_id):
            return "owner"

        if self.is_admin:
            return "admin_supervision"

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé : vous devez être le propriétaire de la ressource",
        )


async def verify_token(token: str) -> dict:
    """
    Verify JWT token with Keycloak.

    Validates:
    - Token signature and expiration (via decode_token)
    - iss (issuer) - must be from our Keycloak realm
    - azp (authorized party) - must be from allowed frontend clients
    - aud (audience) - must include this service or be 'account'
    """
    with tracer.start_as_current_span("verify_keycloak_token") as span:
        try:
            # Decode and verify token with Keycloak (validate=True ensures full verification)
            token_info = keycloak_openid.decode_token(token, validate=True)

            # Validate iss (issuer) - who issued this token
            # Skip in DEBUG mode as issuer URL varies (localhost vs keycloak vs host.docker.internal)
            iss = token_info.get("iss")
            if not settings.DEBUG:
                # Production: Must be from our Keycloak realm
                expected_issuer = (
                    f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/realms/{settings.KEYCLOAK_REALM}"
                )
                if not iss or iss != expected_issuer:
                    logger.error(f"Invalid issuer in token: {iss}. Expected: {expected_issuer}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=f"Token from unauthorized issuer: {iss}",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            else:
                # Development: Log issuer for debugging but don't validate
                logger.debug(f"DEBUG mode: Skipping issuer validation. Token issuer: {iss}")

            # Validate azp (authorized party) - who requested this token
            # Only accept tokens from our known frontend clients
            allowed_azp = {
                "apps-africare-provider-portal",  # Healthcare provider portal
                "apps-africare-patient-portal",  # Patient portal
                "apps-africare-admin-portal",  # Admin portal
            }

            azp = token_info.get("azp")
            if not azp or azp not in allowed_azp:
                logger.error(f"Invalid azp in token: {azp}. Expected one of: {allowed_azp}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Token not authorized for this service (invalid azp: {azp})",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Validate aud (audience) - who can use this token
            # Accept tokens meant for this service or the generic 'account' audience
            aud = token_info.get("aud", [])
            if isinstance(aud, str):
                aud = [aud]

            valid_audiences = {"account", settings.KEYCLOAK_CLIENT_ID}
            if not any(audience in valid_audiences for audience in aud):
                logger.error(
                    f"Invalid audience in token: {aud}. Expected one of: {valid_audiences}"
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Token not intended for this service (invalid audience: {aud})",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            span.set_attribute("auth.user_id", token_info.get("sub"))
            span.set_attribute("auth.iss", iss)
            span.set_attribute("auth.azp", azp)
            span.set_attribute("auth.aud", str(aud))

            logger.debug(
                f"Token validated successfully - iss: {iss}, azp: {azp}, aud: {aud}, user: {token_info.get('sub')}"
            )
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


async def extract_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)] = None,
) -> str:
    """
    Extract JWT token from multiple sources (for SSE and HTTP compatibility).

    Token extraction priority:
    1. Authorization header: Bearer <token> (standard for HTTP requests)
    2. Query parameter: ?token=<token> (for SSE/EventSource)
    3. Cookie: auth_token (alternative for SSE)

    This multi-source approach enables:
    - Standard HTTP requests: Use Authorization header (interceptor-compatible)
    - SSE connections: Use query parameter (EventSource limitation)
    - Cookie-based auth: Use cookie (alternative for browsers)

    Args:
        request: FastAPI Request object
        credentials: HTTPAuthorizationCredentials from Bearer scheme (optional)

    Returns:
        JWT token string

    Raises:
        HTTPException: If no token found in any source
    """
    # Source 1: Authorization header (Bearer token)
    if credentials:
        logger.debug("Token extracted from Authorization header")
        return credentials.credentials

    # Source 2: Query parameter (?token=<jwt>)
    token = request.query_params.get("token")
    if token:
        logger.debug("Token extracted from query parameter")
        return token

    # Source 3: Cookie (auth_token)
    token = request.cookies.get("auth_token")
    if token:
        logger.debug("Token extracted from cookie")
        return token

    # No token found in any source
    logger.warning("No authentication token found in request")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide token via Authorization header, query parameter, or cookie.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_token_data(token: Annotated[str, Depends(extract_token)]) -> dict:
    """Extract and verify token from multiple sources."""
    return await verify_token(token)


async def get_current_user(token_data: Annotated[dict, Depends(get_token_data)]) -> User:
    """Get current user from verified Keycloak token."""
    with tracer.start_as_current_span("get_current_user") as span:
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

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
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
