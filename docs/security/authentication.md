# Security and Authorization

This document describes the authentication and authorization system used in AfriCare microservices.

## Table of Contents

- [Authentication](#authentication)
- [Authorization](#authorization)
- [Role-Based Access Control](#role-based-access-control)
- [Security Dependencies](#security-dependencies)
- [Usage Examples](#usage-examples)
- [Best Practices](#best-practices)

## Authentication

### Keycloak Integration

AfriCare uses **Keycloak** for centralized authentication and identity management. All protected endpoints validate JWT tokens issued by Keycloak.

**Configuration** (`app/core/config.py`):

```python
KEYCLOAK_SERVER_URL: str
KEYCLOAK_REALM: str
KEYCLOAK_CLIENT_ID: str
KEYCLOAK_CLIENT_SECRET: str
```

### JWT Token Validation

The `verify_token()` function validates JWT tokens with Keycloak:

```python
from app.core.security import verify_token

async def verify_token(token: str) -> dict:
    """Verify JWT token with Keycloak."""
    # Decodes and validates token
    # Returns token payload with user claims
```

**Token Payload Structure**:

```json
{
  "sub": "user-keycloak-id",
  "email": "user@example.com",
  "preferred_username": "username",
  "given_name": "First",
  "family_name": "Last",
  "realm_access": {
    "roles": ["patient", "user"]
  },
  "resource_access": {
    "core-africare-service": {
      "roles": ["service-specific-role"]
    }
  }
}
```

### User Model

The `User` Pydantic model represents authenticated users:

```python
class User(BaseModel):
    sub: str  # Keycloak user ID
    email: Optional[str] = None
    preferred_username: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    realm_access: Optional[dict] = None  # Realm-level roles
    resource_access: Optional[dict] = None  # Client-specific roles
```

## Authorization

### Role Sources

AfriCare checks roles from two sources:

1. **Realm Roles** (`realm_access.roles`): Global roles assigned at the Keycloak realm level
2. **Client Roles** (`resource_access.{client_id}.roles`): Service-specific roles

### Role Checking Logic

The system checks **both** realm roles and client-specific roles. A user has a role if it exists in **either** location.

```python
def check_user_role(user: User, required_role: str) -> bool:
    """Check if user has required role in realm_access or resource_access."""
    # Checks both realm and client roles
    # Returns True if role found in either location
```

## Role-Based Access Control

### The `require_roles()` Decorator

The `require_roles()` function is a **dependency factory** that creates FastAPI dependencies for role-based access control.

**Function Signature**:

```python
def require_roles(*roles: str, require_all: bool = False) -> Callable
```

**Parameters**:

- `*roles`: One or more role names required for access
- `require_all`: Boolean flag for AND/OR logic
  - `False` (default): User needs **ANY** of the specified roles (OR logic)
  - `True`: User needs **ALL** of the specified roles (AND logic)

**Returns**: FastAPI dependency function that validates user roles

### OR Logic (Default): Any Role

By default, `require_roles()` uses **OR logic** - the user needs **at least one** of the specified roles.

```python
from fastapi import APIRouter, Depends
from app.core.security import require_roles

router = APIRouter()

# User needs EITHER "patient" OR "professional" role
@router.get("/health-data", dependencies=[Depends(require_roles("patient", "professional"))])
async def get_health_data():
    return {"data": "sensitive health information"}
```

### AND Logic: All Roles

Set `require_all=True` to require **all** specified roles (AND logic).

```python
# User needs BOTH "admin" AND "manager" roles
@router.delete("/critical-data", dependencies=[Depends(require_roles("admin", "manager", require_all=True))])
async def delete_critical_data():
    return {"status": "deleted"}
```

### Single Role Check

For single role requirements, just pass one role:

```python
# User needs "patient" role only
@router.get("/patient-portal", dependencies=[Depends(require_roles("patient"))])
async def patient_portal():
    return {"portal": "patient dashboard"}
```

## Security Dependencies

### Available Dependencies

The `app/core/security.py` module provides several dependencies:

#### 1. `get_token_data()`

Extracts and verifies JWT token from HTTP Bearer header.

```python
from app.core.security import get_token_data

@router.get("/me")
async def get_current_user_info(token_data: dict = Depends(get_token_data)):
    return token_data
```

#### 2. `get_current_user()`

Returns authenticated `User` object from validated token.

```python
from app.core.security import get_current_user, User

@router.get("/profile")
async def get_profile(current_user: User = Depends(get_current_user)):
    return {"user_id": current_user.sub, "email": current_user.email}
```

#### 3. `require_roles()`

Validates that authenticated user has required role(s).

```python
from app.core.security import require_roles

# OR logic - user needs patient OR professional
@router.get("/data", dependencies=[Depends(require_roles("patient", "professional"))])

# AND logic - user needs admin AND manager
@router.delete("/critical", dependencies=[Depends(require_roles("admin", "manager", require_all=True))])
```

#### 4. `get_current_patient()` (Convenience)

Pre-configured dependency for patient role validation.

```python
from app.core.security import get_current_patient, User

@router.get("/patient-records")
async def get_patient_records(patient: User = Depends(get_current_patient)):
    # Guaranteed to have "patient" role
    return {"patient_id": patient.sub}
```

#### 5. `get_current_professional()` (Convenience)

Pre-configured dependency for professional role validation.

```python
from app.core.security import get_current_professional, User

@router.post("/diagnoses")
async def create_diagnosis(professional: User = Depends(get_current_professional)):
    # Guaranteed to have "professional" role
    return {"professional_id": professional.sub}
```

## Usage Examples

### Example 1: Public Endpoint (No Authentication)

```python
@router.get("/health")
async def health_check():
    """Public health check endpoint - no authentication required."""
    return {"status": "healthy"}
```

### Example 2: Authenticated Endpoint (Any Authenticated User)

```python
from app.core.security import get_current_user, User

@router.get("/profile")
async def get_user_profile(current_user: User = Depends(get_current_user)):
    """Requires valid JWT token - any authenticated user can access."""
    return {
        "user_id": current_user.sub,
        "email": current_user.email,
        "username": current_user.preferred_username
    }
```

### Example 3: Single Role Requirement

```python
from app.core.security import require_roles

@router.get("/patient-dashboard", dependencies=[Depends(require_roles("patient"))])
async def patient_dashboard():
    """Only users with 'patient' role can access."""
    return {"dashboard": "patient view"}
```

### Example 4: Multiple Roles (OR Logic)

```python
@router.get("/medical-records", dependencies=[Depends(require_roles("patient", "professional", "admin"))])
async def get_medical_records():
    """Users with patient OR professional OR admin role can access."""
    return {"records": [...]}
```

### Example 5: Multiple Roles (AND Logic)

```python
@router.delete("/system-config", dependencies=[Depends(require_roles("admin", "super_admin", require_all=True))])
async def delete_system_config():
    """Users must have BOTH admin AND super_admin roles."""
    return {"status": "configuration deleted"}
```

### Example 6: Role Check with User Data

```python
from app.core.security import require_roles, User

@router.post("/appointments")
async def create_appointment(current_user: User = Depends(require_roles("patient", "professional"))):
    """
    Requires patient OR professional role.
    Also returns the authenticated user object for business logic.
    """
    return {
        "appointment_id": "123",
        "created_by": current_user.sub,
        "user_role": "determined_in_business_logic"
    }
```

### Example 7: Using Convenience Dependencies

```python
from app.core.security import get_current_patient, get_current_professional, User

@router.get("/patient-records")
async def get_patient_records(patient: User = Depends(get_current_patient)):
    """Simplified patient role check using convenience dependency."""
    return {"patient_id": patient.sub, "records": [...]}

@router.post("/prescriptions")
async def create_prescription(professional: User = Depends(get_current_professional)):
    """Simplified professional role check using convenience dependency."""
    return {"prescription_id": "456", "prescribed_by": professional.sub}
```

### Example 8: Router-Level Security

```python
from fastapi import APIRouter, Depends
from app.core.security import require_roles

# Apply role requirement to ALL routes in this router
router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_roles("admin"))]
)

@router.get("/users")
async def list_users():
    """Inherits admin role requirement from router."""
    return {"users": [...]}

@router.delete("/users/{user_id}")
async def delete_user(user_id: str):
    """Also requires admin role from router dependency."""
    return {"status": "user deleted"}
```

## Best Practices

### 1. Use Descriptive Role Names

```python
# Good
require_roles("professional", "admin")

# Avoid generic names
require_roles("user", "role1")
```

### 2. Prefer Router-Level Security for Consistent Access

```python
# Apply security to entire router
admin_router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_roles("admin"))]
)
```

### 3. Use Convenience Dependencies for Common Roles

```python
# For frequently used single role checks
from app.core.security import get_current_patient, get_current_professional

# Instead of
@router.get("/", dependencies=[Depends(require_roles("patient"))])

# Use
@router.get("/")
async def endpoint(patient: User = Depends(get_current_patient)):
    pass
```

### 4. Combine with Other Dependencies

```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.security import require_roles, User

@router.post("/appointments")
async def create_appointment(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_roles("patient", "professional"))
):
    """Combines database session and role-based access control."""
    # Business logic with database access and authenticated user
    pass
```

### 5. Audit Logging with User Context

```python
from app.core.security import get_current_user, User
from app.core.events import publish
from datetime import datetime, UTC

@router.post("/sensitive-action", dependencies=[Depends(require_roles("admin"))])
async def sensitive_action(current_user: User = Depends(get_current_user)):
    # Perform action
    result = perform_action()

    # Audit log with Keycloak user ID
    await publish("audit.user_action.logged", {
        "event_type": "sensitive_action_performed",
        "resource_type": "system",
        "user_id": current_user.sub,  # Keycloak user ID
        "action": "create",
        "timestamp": datetime.now(UTC).isoformat()
    })

    return result
```

### 6. Handle Role Conflicts Gracefully

```python
# If business logic requires checking which specific role user has
@router.get("/dashboard")
async def get_dashboard(current_user: User = Depends(require_roles("patient", "professional"))):
    # Determine which dashboard to show based on user's roles
    if check_user_role(current_user, "professional"):
        return {"dashboard": "professional_view"}
    elif check_user_role(current_user, "patient"):
        return {"dashboard": "patient_view"}
    else:
        return {"dashboard": "default_view"}
```

### 7. Document Role Requirements in OpenAPI

```python
@router.get(
    "/admin-only",
    dependencies=[Depends(require_roles("admin"))],
    summary="Admin-only endpoint",
    description="This endpoint requires the 'admin' role. Only administrators can access.",
    responses={
        403: {"description": "Forbidden - User does not have required role"}
    }
)
async def admin_endpoint():
    return {"data": "admin data"}
```

## OpenTelemetry Integration

The `require_roles()` dependency automatically creates OpenTelemetry spans with the following attributes:

- `auth.required_roles`: Comma-separated list of required roles
- `auth.require_all`: Boolean indicating AND/OR logic
- `auth.user_id`: Keycloak user ID
- `auth.user_roles`: Comma-separated list of user's roles
- `auth.access_granted`: Boolean indicating successful authorization
- `auth.access_denied`: Boolean indicating failed authorization (if applicable)
- `auth.missing_roles`: Comma-separated list of missing roles (if access denied)

This provides full observability for security and compliance auditing.

## Error Responses

### 401 Unauthorized

Returned when JWT token is invalid or missing:

```json
{
  "detail": "Invalid token"
}
```

### 403 Forbidden

Returned when user lacks required role(s):

**OR Logic** (default):

```json
{
  "detail": "Access denied. Required roles: patient, professional"
}
```

**AND Logic** (`require_all=True`):

```json
{
  "detail": "Access denied. All required roles must be present: admin, manager"
}
```

## Migration Guide

### Upgrading from Old Role Check Pattern

**Old Pattern**:

```python
@router.get("/endpoint")
async def endpoint(patient: User = Depends(get_current_patient)):
    pass
```

**New Pattern (Option 1 - Keep using convenience dependency)**:

```python
@router.get("/endpoint")
async def endpoint(patient: User = Depends(get_current_patient)):
    pass  # Still works - convenience dependencies use require_roles internally
```

**New Pattern (Option 2 - Use require_roles directly)**:

```python
@router.get("/endpoint", dependencies=[Depends(require_roles("patient"))])
async def endpoint():
    pass
```

**New Pattern (Option 3 - Multiple roles)**:

```python
@router.get("/endpoint", dependencies=[Depends(require_roles("patient", "professional"))])
async def endpoint():
    pass
```

The convenience dependencies (`get_current_patient`, `get_current_professional`) have been updated to use `require_roles()` internally, ensuring **backward compatibility**.
