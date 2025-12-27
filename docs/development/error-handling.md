# RFC 9457 Problem Details for HTTP APIs

Ce document décrit l'implémentation de la RFC 9457 (Problem Details for HTTP APIs) dans les microservices AfriCare.

## Vue d'ensemble

La RFC 9457 définit un format JSON standardisé pour les réponses d'erreur HTTP. Ce format permet de :

- **Standardiser les erreurs** : Format cohérent à travers tous les microservices
- **Faciliter le débogage** : Informations structurées pour diagnostiquer les problèmes
- **Améliorer l'expérience développeur** : Réponses prévisibles et documentées
- **Support de l'observabilité** : Intégration avec OpenTelemetry (trace_id)

## Référence

- **RFC 9457** : [https://www.rfc-editor.org/rfc/rfc9457.html](https://www.rfc-editor.org/rfc/rfc9457.html)
- **Swagger Blog** : [https://swagger.io/blog/problem-details-rfc9457-api-error-handling](https://swagger.io/blog/problem-details-rfc9457-api-error-handling)

## Structure d'une réponse Problem Details

### Champs obligatoires

```json
{
  "type": "https://africare.app/errors/not-found",
  "title": "Not Found",
  "status": 404
}
```

- **type** : URI identifiant le type de problème (défaut : `about:blank`)
- **title** : Résumé court, lisible par l'humain, du type de problème
- **status** : Code de statut HTTP généré par le serveur

### Champs optionnels

```json
{
  "type": "https://africare.app/errors/not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "User with ID 12345 not found in database",
  "instance": "/api/v1/users/12345"
}
```

- **detail** : Explication détaillée spécifique à cette occurrence du problème
- **instance** : URI identifiant l'occurrence spécifique du problème

### Extensions AfriCare

Les réponses Problem Details peuvent inclure des extensions pour fournir des informations supplémentaires :

```json
{
  "type": "https://africare.app/errors/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "2 validation error(s) detected",
  "instance": "/api/v1/users",
  "trace_id": "abc123def456789",
  "timestamp": "2025-10-09T09:50:56.209911+00:00",
  "errors": [
    {
      "loc": ["body", "email"],
      "msg": "Invalid email format",
      "type": "value_error"
    },
    {
      "loc": ["body", "age"],
      "msg": "Age must be between 0 and 150",
      "type": "value_error"
    }
  ]
}
```

Extensions standard AfriCare :

- **trace_id** : Identifiant de trace OpenTelemetry pour corrélation
- **timestamp** : Timestamp UTC de l'erreur au format ISO 8601 (automatiquement ajouté)
- **errors** : Liste des erreurs de validation (pour erreurs 422)
- **resource_type** : Type de ressource concernée
- **resource_id** : Identifiant de la ressource
- **conflicting_resource** : Ressource en conflit (erreurs 409)

### Content-Type

Toutes les réponses d'erreur utilisent le Content-Type standardisé :

```http
Content-Type: application/problem+json
```

## Architecture de l'implémentation

### Composants

1. **ProblemDetail** (`app/core/exceptions.py`) : Modèle Pydantic pour la structure RFC 9457
2. **AfriCareException** (`app/core/exceptions.py`) : Exception de base compatible RFC 9457
3. **Exceptions pré-configurées** (`app/core/exceptions.py`) : ValidationError, NotFoundError, etc.
4. **ProblemDetailsMiddleware** (`app/core/middlewares/problem_details.py`) : Middleware FastAPI
5. **Schémas OpenAPI** (`app/schemas/responses.py`) : Modèles pour documentation OpenAPI
6. **COMMON_RESPONSES** (`app/schemas/responses.py`) : Réponses par défaut (400, 401, 404, 409, 422, 500)

### Flux de traitement

```
Requête HTTP
    ↓
FastAPI Application
    ↓
Endpoint Handler
    ↓
Exception levée
    ↓
ProblemDetailsMiddleware ← Intercepte TOUTES les exceptions
    ↓
Conversion en RFC 9457
    ↓
Réponse JSON + Content-Type: application/problem+json
```

## Utilisation

### Configuration automatique des réponses OpenAPI

Les réponses RFC 9457 sont **automatiquement documentées** dans OpenAPI via `COMMON_RESPONSES` :

```python
# app/api/v1/api.py
from fastapi import APIRouter
from app.schemas import COMMON_RESPONSES

# Les réponses RFC 9457 sont appliquées à TOUS les endpoints du router
router = APIRouter(responses=COMMON_RESPONSES)
```

**Avantages** :

- Pas besoin de répéter `responses={**COMMON_RESPONSES}` sur chaque endpoint
- Documentation OpenAPI cohérente automatique (codes 400, 401, 404, 409, 422, 500)
- Les endpoints peuvent **étendre** avec des réponses spécifiques

**Extension avec réponses spécifiques** :

```python
@router.post(
    "/users",
    response_model=UserResponse,
    status_code=201,
    responses={
        # Les COMMON_RESPONSES sont héritées automatiquement
        # On ajoute uniquement des réponses spécifiques
        201: {"description": "User created successfully"},
        503: {
            "model": ProblemDetailResponse,
            "description": "Service Unavailable - External system down",
        },
    }
)
async def create_user(user: UserCreate):
    # FastAPI fusionne automatiquement :
    # - COMMON_RESPONSES (400, 401, 404, 409, 422, 500)
    # - Réponses spécifiques (201, 503)
    # Total dans OpenAPI : 200, 201, 400, 401, 404, 409, 422, 500, 503
    ...
```

**Important** : FastAPI **fusionne** automatiquement les réponses :

- COMMON_RESPONSES du router (400, 401, 404, 409, 422, 500)
- Réponses spécifiques de l'endpoint (201, 503, etc.)
- Aucun conflit, aucune surcharge manuelle nécessaire

### Exceptions pré-configurées

Utiliser les exceptions AfriCare pré-configurées pour les cas courants :

```python
from app.core.exceptions import (
    ValidationError,
    UnauthorizedError,
    ForbiddenError,
    NotFoundError,
    ConflictError,
    InternalServerError,
    ServiceUnavailableError,
)

# 400 Bad Request - Validation
@router.post("/users")
async def create_user(user: UserCreate):
    if not user.email:
        raise ValidationError(
            detail="Email is required",
            errors=[
                {"loc": ["body", "email"], "msg": "Field required", "type": "missing"}
            ],
        )

# 401 Unauthorized
@router.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise UnauthorizedError(detail="Valid authentication token required")

# 403 Forbidden
@router.delete("/users/{user_id}")
async def delete_user(user_id: int, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise ForbiddenError(detail="Only administrators can delete users")

# 404 Not Found
@router.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await get_user_from_db(user_id)
    if not user:
        raise NotFoundError(
            detail=f"User with ID {user_id} not found",
            resource_type="user",
            resource_id=str(user_id),
        )
    return user

# 409 Conflict
@router.post("/users")
async def create_user(user: UserCreate):
    existing = await get_user_by_email(user.email)
    if existing:
        raise ConflictError(
            detail=f"User with email {user.email} already exists",
            conflicting_resource=f"/users/{existing.id}",
        )

# 500 Internal Server Error
@router.get("/data")
async def get_data():
    try:
        data = await fetch_external_service()
        return data
    except Exception as e:
        span = trace.get_current_span()
        trace_id = format(span.get_span_context().trace_id, "032x")
        raise InternalServerError(
            detail="Failed to fetch data from external service",
            trace_id=trace_id,
        )

# 503 Service Unavailable
@router.get("/health")
async def health_check():
    if not await check_database_connection():
        raise ServiceUnavailableError(
            detail="Database connection unavailable",
            retry_after=60,  # Retry after 60 seconds
        )
```

### Exception personnalisée

Pour des cas spécifiques non couverts par les exceptions pré-configurées :

```python
from app.core.exceptions import AfriCareException

@router.post("/orders/{order_id}/cancel")
async def cancel_order(order_id: int):
    order = await get_order(order_id)

    if order.status == "shipped":
        raise AfriCareException(
            status_code=422,
            title="Order Cannot Be Cancelled",
            detail=f"Order {order_id} has already been shipped and cannot be cancelled",
            type_uri="https://africare.app/errors/order-not-cancellable",
            instance=f"/api/v1/orders/{order_id}/cancel",
            order_status=order.status,
            shipped_at=order.shipped_at.isoformat(),
        )
```

### HTTPException standard

Les HTTPException de FastAPI sont automatiquement converties en RFC 9457 :

```python
from fastapi import HTTPException

@router.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await get_user_from_db(user_id)
    if not user:
        # Automatiquement converti en RFC 9457 par le middleware
        raise HTTPException(status_code=404, detail="User not found")
    return user
```

**Réponse automatique** :

```json
{
  "type": "about:blank",
  "title": "Not Found",
  "status": 404,
  "detail": "User not found",
  "instance": "/api/v1/users/12345",
  "trace_id": "abc123def456789"
}
```

### Erreurs de validation Pydantic

Les `RequestValidationError` de Pydantic sont automatiquement converties :

```python
from pydantic import BaseModel, EmailStr

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    age: int

@router.post("/users")
async def create_user(user: UserCreate):
    # Validation automatique par Pydantic
    # Si invalide, RequestValidationError est levée
    # Middleware convertit en RFC 9457
    result = await create_user_service(user)
    return result
```

**Réponse automatique pour données invalides** :

```json
{
  "type": "https://africare.app/errors/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "2 validation error(s) detected",
  "instance": "/api/v1/users",
  "trace_id": "abc123def456789",
  "errors": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    },
    {
      "loc": ["body", "age"],
      "msg": "ensure this value is greater than or equal to 0",
      "type": "value_error.number.not_ge"
    }
  ]
}
```

## Intégration OpenTelemetry

Le middleware ajoute automatiquement le `trace_id` OpenTelemetry à toutes les réponses d'erreur :

```python
from opentelemetry import trace

@router.post("/process")
async def process_data(data: dict):
    span = trace.get_current_span()
    span.set_attribute("data.size", len(data))

    try:
        result = await process_data_service(data)
        return result
    except Exception as e:
        # Le middleware ajoute automatiquement trace_id
        # Pas besoin de le faire manuellement
        span.record_exception(e)
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
        raise
```

**Réponse avec trace_id** :

```json
{
  "type": "https://africare.app/errors/internal-server-error",
  "title": "Internal Server Error",
  "status": 500,
  "detail": "An unexpected error occurred. Please contact support if the problem persists.",
  "instance": "/api/v1/process",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
}
```

Le `trace_id` permet de corréler les erreurs avec les traces dans Grafana/Tempo.

## Configuration du middleware

Le middleware est activé par défaut dans `app/main.py` :

```python
from app.core.middlewares import ProblemDetailsMiddleware

app = FastAPI(...)

# Middleware RFC 9457 (doit être le premier pour intercepter toutes les erreurs)
app.add_middleware(ProblemDetailsMiddleware)

# Autres middlewares...
app.add_middleware(CORSMiddleware, ...)
```

**Ordre important** : Le `ProblemDetailsMiddleware` doit être ajouté en **premier** pour intercepter toutes les exceptions, y compris celles levées par les autres middlewares.

## Types d'erreur standardisés AfriCare

Tous les microservices AfriCare utilisent les mêmes URIs de type pour cohérence :

| Code | Type URI | Titre | Description |
|------|----------|-------|-------------|
| 400 | `https://africare.app/errors/validation-error` | Validation Error | Données d'entrée invalides |
| 401 | `https://africare.app/errors/unauthorized` | Unauthorized | Authentification requise |
| 403 | `https://africare.app/errors/forbidden` | Forbidden | Accès interdit |
| 404 | `https://africare.app/errors/not-found` | Not Found | Ressource non trouvée |
| 409 | `https://africare.app/errors/conflict` | Conflict | Conflit avec l'état actuel |
| 422 | `https://africare.app/errors/validation-error` | Validation Error | Erreurs de validation Pydantic |
| 500 | `https://africare.app/errors/internal-server-error` | Internal Server Error | Erreur serveur inattendue |
| 503 | `https://africare.app/errors/service-unavailable` | Service Unavailable | Service temporairement indisponible |

## Bonnes pratiques

### 1. Utiliser les exceptions pré-configurées

```python
# ✅ Bon
raise NotFoundError(detail="User not found", resource_type="user", resource_id=str(user_id))

# ❌ Éviter (moins de contexte)
raise HTTPException(status_code=404, detail="Not found")
```

### 2. Fournir des détails spécifiques

```python
# ✅ Bon - Détail spécifique
raise ValidationError(
    detail="Email address is required for user registration",
    errors=[{"loc": ["body", "email"], "msg": "Field required", "type": "missing"}],
)

# ❌ Mauvais - Détail générique
raise ValidationError(detail="Invalid input")
```

### 3. Inclure le contexte pertinent

```python
# ✅ Bon - Contexte riche
raise NotFoundError(
    detail=f"Patient with ID {patient_id} not found in database",
    resource_type="patient",
    resource_id=str(patient_id),
    instance=f"/api/v1/patients/{patient_id}",
)

# ❌ Mauvais - Peu de contexte
raise NotFoundError(detail="Not found")
```

### 4. Logger les erreurs avec contexte

```python
import logging
from opentelemetry import trace

logger = logging.getLogger(__name__)

@router.post("/orders")
async def create_order(order: OrderCreate):
    try:
        result = await create_order_service(order)
        return result
    except ConflictError as e:
        # Erreur métier attendue - log en WARNING
        logger.warning(
            f"Order creation conflict: {e.problem_detail.detail}",
            extra={
                "order_data": order.model_dump(),
                "conflict_detail": e.problem_detail.detail,
            },
        )
        raise
    except Exception as e:
        # Erreur inattendue - log en ERROR avec stack trace
        logger.error(
            f"Unexpected error creating order: {str(e)}",
            exc_info=e,
            extra={"order_data": order.model_dump()},
        )
        raise
```

### 5. Ne pas exposer d'informations sensibles

```python
# ✅ Bon - Détail générique en production
raise InternalServerError(
    detail="Database operation failed. Please contact support.",
    trace_id=trace_id,
)

# ❌ DANGER - Exposition d'informations sensibles
raise InternalServerError(
    detail=f"PostgreSQL error: FATAL: password authentication failed for user '{db_user}'"
)
```

### 6. Utiliser les extensions pour le contexte additionnel

```python
# ✅ Bon - Extensions pour contexte riche
raise AfriCareException(
    status_code=422,
    title="Appointment Conflict",
    detail="Appointment slot is already booked",
    type_uri="https://africare.app/errors/appointment-conflict",
    existing_appointment_id="12345",
    requested_slot="2025-10-15T10:00:00Z",
    available_slots=["2025-10-15T11:00:00Z", "2025-10-15T14:00:00Z"],
)
```

## Tests

Les tests unitaires sont disponibles dans `tests/test_problem_details.py`.

Exécuter les tests :

```bash
# Tous les tests RFC 9457
pytest tests/test_problem_details.py -v

# Tests spécifiques
pytest tests/test_problem_details.py::TestProblemDetailsMiddleware::test_http_exception_conversion -v
pytest tests/test_problem_details.py::TestAfriCareExceptions -v

# Avec couverture
pytest tests/test_problem_details.py --cov=app.core.exceptions --cov=app.core.middlewares --cov-report=term-missing
```

## Migration depuis les réponses d'erreur anciennes

Si vous avez du code existant avec des réponses d'erreur personnalisées :

### Avant (ancien format)

```python
@router.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await get_user_from_db(user_id)
    if not user:
        return JSONResponse(
            status_code=404,
            content={"error": "User not found", "user_id": user_id},
        )
    return user
```

### Après (RFC 9457)

```python
from app.core.exceptions import NotFoundError

@router.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await get_user_from_db(user_id)
    if not user:
        raise NotFoundError(
            detail=f"User with ID {user_id} not found",
            resource_type="user",
            resource_id=str(user_id),
        )
    return user
```

**Avantages** :

- Format standardisé RFC 9457
- Intégration automatique OpenTelemetry (trace_id)
- Content-Type correct (`application/problem+json`)
- Meilleure observabilité et débogage

## Exemples de réponses

### Validation Error (400)

```http
POST /api/v1/users
Content-Type: application/json

{
  "name": "John",
  "email": "invalid-email",
  "age": -5
}
```

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/problem+json

{
  "type": "https://africare.app/errors/validation-error",
  "title": "Validation Error",
  "status": 422,
  "detail": "2 validation error(s) detected",
  "instance": "/api/v1/users",
  "trace_id": "abc123def456789",
  "errors": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    },
    {
      "loc": ["body", "age"],
      "msg": "ensure this value is greater than or equal to 0",
      "type": "value_error.number.not_ge"
    }
  ]
}
```

### Not Found (404)

```http
GET /api/v1/users/12345
```

```http
HTTP/1.1 404 Not Found
Content-Type: application/problem+json

{
  "type": "https://africare.app/errors/not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "User with ID 12345 not found",
  "instance": "/api/v1/users/12345",
  "trace_id": "abc123def456789",
  "resource_type": "user",
  "resource_id": "12345"
}
```

### Unauthorized (401)

```http
GET /api/v1/profile
Authorization: Bearer invalid-token
```

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/problem+json
WWW-Authenticate: Bearer

{
  "type": "https://africare.app/errors/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "Invalid or expired authentication token",
  "instance": "/api/v1/profile",
  "trace_id": "abc123def456789"
}
```

### Conflict (409)

```http
POST /api/v1/users
Content-Type: application/json

{
  "name": "John Doe",
  "email": "john@example.com"
}
```

```http
HTTP/1.1 409 Conflict
Content-Type: application/problem+json

{
  "type": "https://africare.app/errors/conflict",
  "title": "Conflict",
  "status": 409,
  "detail": "User with email john@example.com already exists",
  "instance": "/api/v1/users",
  "trace_id": "abc123def456789",
  "conflicting_resource": "/api/v1/users/67890"
}
```

### Internal Server Error (500)

```http
GET /api/v1/data
```

```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/problem+json

{
  "type": "https://africare.app/errors/internal-server-error",
  "title": "Internal Server Error",
  "status": 500,
  "detail": "An unexpected error occurred. Please contact support if the problem persists.",
  "instance": "/api/v1/data",
  "trace_id": "abc123def456789"
}
```

## Références

- [RFC 9457 - Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc9457.html)
- [Swagger Blog - RFC 9457 Error Handling](https://swagger.io/blog/problem-details-rfc9457-api-error-handling)
- [FastAPI Exception Handling](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
