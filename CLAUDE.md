# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Service Overview

This is **core-africare-identity** - a core AfriCare microservice.

- **Service Type**: core (foundational business logic service)
- **Service Slug**: identity
- **Description**: Identity management and Keycloak integration
- **Version**: 0.1.0

## Common Development Commands

### Setup and Development
```bash
make install                    # Install dependencies with Poetry + OpenTelemetry bootstrap
make run                       # Start development server on port 8001
make run PORT=8080            # Start server on specific port
```

### Code Quality
```bash
make lint                     # Check code with ruff (no changes)
make lint-fix                 # Auto-fix code with ruff format
make test                     # Run pytest with coverage report
```

### Database Operations
```bash
# Méthode 1: Poetry (développement local)
make migrate MESSAGE="Add user table"  # Create new Alembic migration
make migrate-up                        # Apply all pending migrations
make migrate-down                      # Rollback last migration
make migrate-history                   # Show migration history
make migrate-current                   # Show current migration status

# Méthode 2: Docker Compose (environnement conteneurisé)
make migrate-docker MESSAGE="Add user table"  # Create migration via Docker
make migrate-up-docker                         # Apply migrations via Docker
make migrate-down-docker                       # Rollback via Docker
make migrate-history-docker                    # Show history via Docker
make migrate-current-docker                    # Show status via Docker
```
### Testing Commands
```bash
# Tests d'intégration (avec services Docker réels)
make test-integration              # PostgreSQL + Redis sur ports exotiques
make test-services-up             # Démarrer services de test
make test-services-down           # Arrêter services de test

# Tests unitaires (mocks, pas de services externes)
make test-unit                    # Tests rapides sans dépendances

# Tous les tests (unit + integration)
make test-all                     # Démarre services, exécute tout, arrête services

# Tests spécifiques
poetry run pytest tests/test_events.py -v                        # Fichier spécifique
poetry run pytest tests/test_events.py::test_publish_event -v   # Test unique
poetry run pytest -k "event" -v                                  # Pattern matching

# Tests par marqueur
poetry run pytest -m integration -v        # Tests d'intégration uniquement
poetry run pytest -m "not integration" -v  # Tests unitaires uniquement

# Couverture de code
poetry run pytest --cov=app --cov-report=html --cov-report=term-missing
# Rapport HTML dans htmlcov/index.html
```

### Utilities
```bash
make clean                    # Remove __pycache__, .pyc files, coverage files
make help                     # Show all available commands
```

## Architecture Overview

### Service Structure

```
core-africare-identity/
├── app/
│   ├── main.py              # FastAPI app with lifespan management
│   ├── core/                # Cross-cutting concerns
│   │   ├── config.py        # Pydantic settings (env vars, OpenTelemetry)
│   │   ├── database.py      # SQLAlchemy 2.0 async setup
│   │   ├── events.py        # Redis Pub/Sub messaging (Phase 1 MVP)
│   │   └── security.py      # JWT auth and security utilities
│   ├── infrastructure/      # External service integrations
│   │   └── fhir/            # HAPI FHIR integration
│   │       ├── client.py    # Async HTTP client
│   │       ├── config.py    # FHIR settings
│   │       ├── identifiers.py  # FHIR identifier systems
│   │       ├── exceptions.py   # FHIR error types
│   │       └── mappers/     # Pydantic <-> FHIR mappers
│   │           ├── patient_mapper.py
│   │           └── professional_mapper.py
│   ├── api/
│   │   └── v1/              # API version 1 routes
│   │       ├── api.py       # Main router aggregation
│   │       ├── endpoints/   # Individual endpoint modules
│   │       └── health.py    # Health check endpoint
│   ├── models/              # SQLAlchemy 2.0 database tables (GDPR metadata)
│   ├── schemas/             # Pydantic request/response models
│   └── services/            # Business logic and event handlers
│       └── event_service.py # Event handlers with @subscribe decorators
├── alembic/                 # Database migration files
├── docs/                    # Service-specific documentation
│   ├── database.md          # Database setup and usage
│   ├── events.md            # Event system documentation
│   ├── fhir-architecture.md # FHIR hybrid architecture
│   └── testing.md           # Testing infrastructure and patterns
├── tests/                   # Test suite
│   ├── integration/         # Tests d'intégration (PostgreSQL + Redis réels)
│   │   ├── test_database_integration.py  # 8 tests PostgreSQL
│   │   └── test_redis_integration.py     # 12 tests Redis
│   ├── unit/                # Tests unitaires (avec mocks)
│   └── conftest.py          # Fixtures pytest partagées
├── Makefile                 # Development commands (include test commands)
├── pyproject.toml          # Poetry dependencies and tool config
├── alembic.ini             # Alembic configuration
├── init-db.sql             # PostgreSQL database initialization
├── docker-compose.yaml     # Local development stack (PostgreSQL + Redis)
└── docker-compose.test.yaml # Test services (ports exotiques 5433, 6380)
```

### Key Technologies

- **FastAPI**: Async web framework with automatic OpenAPI docs
- **SQLAlchemy 2.0**: Modern async ORM with Mapped[] annotations
- **Alembic**: Database schema migrations
- **PostgreSQL 18**: Relational database with full ACID compliance
- **Redis 7**: Messaging Pub/Sub et cache (Phase 1 MVP)
- **OpenTelemetry**: Distributed tracing and observability
- **Poetry**: Dependency management and packaging
- **Ruff**: Code linting and formatting
- **pytest**: Testing framework with async support + integration tests
- **Docker Compose**: Services de développement et de test isolés
- **HAPI FHIR**: Source of truth for Patient/Practitioner demographics
- **fhir-resources**: FHIR R4 resource models (Pydantic v2)
- **httpx**: Async HTTP client for FHIR operations

## FHIR Hybrid Architecture

Le service utilise une **architecture hybride FHIR** où:
- **HAPI FHIR** stocke les données démographiques (Patient, Practitioner)
- **PostgreSQL** stocke les métadonnées GDPR locales

### Composants FHIR

```
app/infrastructure/fhir/
├── __init__.py
├── client.py           # Client HTTP async (httpx + retry)
├── config.py           # Configuration FHIR
├── identifiers.py      # Systèmes d'identifiants FHIR
├── exceptions.py       # Exceptions FHIR typées
└── mappers/
    ├── __init__.py
    ├── patient_mapper.py       # PatientCreate <-> FHIR Patient
    └── professional_mapper.py  # ProfessionalCreate <-> FHIR Practitioner
```

### Modèles GDPR Locaux

```python
# app/models/gdpr_metadata.py
class PatientGdprMetadata(Base):
    id: Mapped[int]                    # ID numérique (rétro-compat API)
    fhir_resource_id: Mapped[str]      # UUID FHIR Patient
    keycloak_user_id: Mapped[str]      # Lookup rapide
    is_verified: Mapped[bool]
    under_investigation: Mapped[bool]  # Blocage suppression
    soft_deleted_at: Mapped[datetime]  # Période de grâce 7j
    anonymized_at: Mapped[datetime]    # Anonymisation définitive
    correlation_hash: Mapped[str]      # Détection retour

class ProfessionalGdprMetadata(Base):
    # Mêmes champs + is_available, digital_signature
```

### Pattern d'Orchestration

```python
async def create_patient(db, fhir_client, patient_data, current_user_id):
    # 1. Mapper vers FHIR
    fhir_patient = PatientMapper.to_fhir(patient_data)
    # 2. Créer dans HAPI FHIR
    created_fhir = await fhir_client.create(fhir_patient)
    # 3. Créer métadonnées GDPR locales
    gdpr = PatientGdprMetadata(fhir_resource_id=created_fhir.id, ...)
    db.add(gdpr)
    await db.commit()
    # 4. Retourner avec ID numérique local
    return PatientMapper.from_fhir(created_fhir, local_id=gdpr.id, ...)
```

### Rétro-compatibilité API

- Mêmes schémas Pydantic (PatientResponse, ProfessionalResponse)
- Mêmes IDs numériques dans les réponses
- Mêmes endpoints sans modification

Voir `docs/fhir-architecture.md` pour plus de détails.

## Event System

### Pure Azure Event Hub Integration

**Configuration** (only 2 variables needed):
```bash
# Method 1: Connection String
AZURE_EVENTHUB_CONNECTION_STRING=

# Method 2: Managed Identity with FQDN
AZURE_EVENTHUB_NAMESPACE=africare.servicebus.windows.net
```

**Publishing Events:**
```python
from app.core.events import publish

# Simple publish
await publish("identity.entity.created", {
    "entity_id": "123",
    "timestamp": datetime.now(UTC).isoformat()
})

# With Pydantic model
from app.schemas.events import EntityCreatedEvent
event = EntityCreatedEvent(entity_id="123", name="Example")
await publish("identity.entity.created", event)
```

**Consuming Events:**
```python
from app.core.events import subscribe

@subscribe("user.created")
async def handle_user_created(payload: dict):
    """Handle user creation events from other services."""
    user_id = payload.get("user_id")
    logger.info(f"Processing new user: {user_id}")

    # Your business logic here
    await initialize_user_data(user_id)
```

**Event Hub Details:**
- **EventHub Name**: `core-africare-identity` (matches service name)
- **Consumer Group**: `$Default`
- **SDK**: Direct usage of `EventHubProducerClient` and `EventHubConsumerClient`
- **Telemetry**: Automatic OpenTelemetry tracing for all events

## Database Integration

### PostgreSQL avec SQLAlchemy 2.0

**Database URL**: `postgresql+asyncpg://core-africare-identity:vd8bveedbnBpMcYr_8qB6A@postgres:5432/core-africare-identity`

**Initialisation Automatique**:
Le fichier `init-db.sql` est automatiquement exécuté au démarrage du conteneur PostgreSQL pour :
- Créer l'utilisateur `core-africare-identity`
- Créer la base de données `core-africare-identity`
- Accorder tous les privilèges

**Engine Creation** (SQLAlchemy 2.0 async pattern):
```python
# app/core/database.py
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

class Base(DeclarativeBase):
    """Base class pour tous les modèles SQLAlchemy."""
    pass

engine = create_async_engine(str(settings.SQLALCHEMY_DATABASE_URI), echo=settings.DEBUG)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session

async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

**Model Definition** (SQLAlchemy 2.0 with Mapped[]):
```python
# app/models/example.py
from typing import Optional
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Example(Base):
    __tablename__ = "examples"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(1000), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

**Database Operations** (async):
```python
# app/services/example_service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.example import Example

async def create_example(db: AsyncSession, name: str, description: str = None) -> Example:
    example = Example(name=name, description=description)
    db.add(example)
    await db.commit()
    await db.refresh(example)
    return example

async def get_example(db: AsyncSession, example_id: int) -> Example | None:
    return await db.get(Example, example_id)

async def get_examples(db: AsyncSession):
    result = await db.execute(select(Example))
    return result.scalars().all()
```

**Migration Workflow:**
```bash
# 1. Create/modify SQLModel tables in app/models/
# 2. Import models in app/models/__init__.py
# 3. Generate migration
make migrate MESSAGE="Add example table"
# 4. Review generated file in alembic/versions/
# 5. Apply migration
make migrate-up
```

**Important**: SQLModel tables must be imported in `app/models/__init__.py` for Alembic auto-detection.

## Configuration Management

### Environment Variables

**Required Settings:**
```bash
# Service Identity
OTEL_SERVICE_NAME=core-africare-identity

# Database
SQLALCHEMY_DATABASE_URI=postgresql+asyncpg://core-africare-identity:vd8bveedbnBpMcYr_8qB6A@postgres:5432/core-africare-identity
# Azure Event Hub (choose one method)
AZURE_EVENTHUB_CONNECTION_STRING=
AZURE_EVENTHUB_NAMESPACE=africare.servicebus.windows.net
AZURE_EVENTHUB_BLOB_STORAGE_CONNECTION_STRING=

# Keycloak Authentication
KEYCLOAK_SERVER_URL=https://keycloak.africare.app/auth
KEYCLOAK_REALM=africare
KEYCLOAK_CLIENT_ID=core-africare-identity
KEYCLOAK_CLIENT_SECRET=cYRi-B9OO2Ufd1h1n1SduA

# HAPI FHIR Server (source of truth for demographics)
HAPI_FHIR_BASE_URL=http://localhost:8080/fhir
HAPI_FHIR_TIMEOUT=30

# OpenTelemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://grafana-otel:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_EXPORTER_OTLP_INSECURE=true
```

**Optional Settings:**
```bash
# Environment
ENVIRONMENT=development  # development|staging|production
DEBUG=false

# API Configuration
API_GATEWAY_URL=http://api-gateway-service:8000

# CORS and Security
ALLOWED_ORIGINS=["http://localhost:3000"]
TRUSTED_HOSTS=["localhost","127.0.0.1"]
```

## API Development Patterns

### API Versioning

Le service supporte **plusieurs versions d'API simultanément** pour permettre une évolution sans rupture.

**Configuration dans `app/core/config.py`:**
```python
# API Versioning - Support multiple versions simultaneously
API_VERSIONS: list[str] = ["v1"]  # Add "v2", "v3" as needed
API_LATEST_VERSION: str = "v1"

# Helper method
def get_api_prefix(self, version: str = None) -> str:
    """Get API prefix for a specific version."""
    version = version or self.API_LATEST_VERSION
    return f"/api/{version}"
```

**Ajout d'une nouvelle version (ex: v2):**

1. **Créer la structure v2:**
```bash
mkdir -p app/api/v2/endpoints
touch app/api/v2/__init__.py
touch app/api/v2/api.py
touch app/api/v2/endpoints/__init__.py
```

2. **Copier et adapter depuis v1:**
```bash
cp app/api/v1/api.py app/api/v2/api.py
# Modifier v2/api.py selon les nouveaux besoins
```

3. **Activer v2 dans `app/main.py`:**
```python
# Import
from app.api.v2 import api as api_v2

# Include router
app.include_router(
    api_v2.router,
    prefix=settings.get_api_prefix("v2"),
    tags=["v2"]
)
```

4. **Mettre à jour la configuration:**
```python
# app/core/config.py
API_VERSIONS: list[str] = ["v1", "v2"]
API_LATEST_VERSION: str = "v2"  # Point to latest
```

**Stratégie de migration:**
- **v1** reste accessible à `/api/v1/*` (pas de breaking change)
- **v2** introduit les nouveaux endpoints à `/api/v2/*`
- Les clients migrent progressivement vers v2
- v1 peut être déprécié (mais reste actif) via `deprecated=True` dans FastAPI
- Communication de la date EOL (End of Life) pour v1

**Exemple avec dépréciation:**
```python
@router.get("/old-endpoint", deprecated=True)
async def old_endpoint():
    """DEPRECATED: Use /api/v2/new-endpoint instead. EOL: 2025-12-31"""
    # Add deprecation header
    response.headers["X-API-Deprecated"] = "true"
    response.headers["X-API-Sunset"] = "2025-12-31"
    return {"message": "This endpoint is deprecated"}
```

### Endpoint Structure

```python
# app/api/v1/endpoints/examples.py
from fastapi import APIRouter, HTTPException
from app.models.example import Example, ExampleCreate, ExampleResponse
from app.services.example_service import create_example, get_example
from app.core.events import publish

router = APIRouter()

@router.post("/", response_model=ExampleResponse)
async def create_example_endpoint(
    example: ExampleCreate
) -> ExampleResponse:
    """Create a new example entity."""
    # Business logic
    created_example = await create_example(example)

    # Publish event
    await publish("identity.example.created", {
        "example_id": str(created_example.id),
        "name": created_example.name,
        "timestamp": datetime.now(UTC).isoformat()
    })

    return ExampleResponse.model_validate(created_example)

@router.get("/{example_id}", response_model=ExampleResponse)
async def get_example_endpoint(example_id: int) -> ExampleResponse:
    """Get an example by ID."""
    example = await get_example(example_id)
    if not example:
        raise HTTPException(status_code=404, detail="Example not found")
    return ExampleResponse.model_validate(example)
```

### Dependency Injection

```python
# app/core/deps.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_session
from app.models.example import Example

async def get_db_session() -> AsyncSession:
    """Database session dependency."""
    async with get_session() as session:
        yield session

# Usage in endpoints
@router.get("/examples")
async def list_examples(
    db: AsyncSession = Depends(get_db_session)
) -> list[ExampleResponse]:
    """List all examples."""
    result = await db.execute(select(Example))
    examples = result.scalars().all()
    return [ExampleResponse.model_validate(ex) for ex in examples]
```

## Testing Patterns

### Test Structure

```python
# tests/test_events.py
import pytest
from unittest.mock import patch
from app.core.events import publish

@pytest.mark.asyncio
async def test_publish_event():
    """Test event publishing."""
    with patch('app.core.events.create_producer_client') as mock_client:
        mock_producer = mock_client.return_value

        await publish("test.event", {"data": "test"})

        mock_producer.send_batch.assert_called_once()
        mock_producer.close.assert_called_once()

# tests/test_services.py
import pytest
from app.models.example import ExampleCreate
from app.services.example_service import create_example

@pytest.mark.asyncio
async def test_create_example():
    """Test business logic."""
    # Setup test data
    example_data = ExampleCreate(name="Test Example", description="Test description")
    result = await create_example(example_data)

    assert result.name == "Test Example"
    assert result.description == "Test description"
    assert result.id is not None
    assert result.created_at is not None
```

### Database Testing

```python
# conftest.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from app.core.database import Base
from app.core.config import settings

# Test engine
test_engine = create_async_engine(
    "sqlite+aiosqlite:///./test.db",  # SQLite pour les tests
    echo=False
)

@pytest.fixture
async def db_session():
    """Provide test database session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(test_engine) as session:
        yield session
        await session.rollback()
```

### Tests d'Intégration

Le service inclut une **infrastructure de tests d'intégration** complète avec services Docker dédiés pour éviter les conflits avec l'environnement de développement.

#### Infrastructure Docker de Test

**Fichier `docker-compose.test.yaml`:**
- Services de test isolés sur **ports exotiques**
- PostgreSQL: port **5433** (au lieu de 5432)
- Redis: port **6380** (au lieu de 6379)
- Évite les conflits avec services de développement

**Démarrage des services de test:**
```bash
# Via make (recommandé)
make test-services-up      # Démarre PostgreSQL + Redis de test
make test-services-status  # Vérifie le statut des services
make test-services-down    # Arrête les services de test

# Via docker-compose
docker-compose -f docker-compose.test.yaml up -d
docker-compose -f docker-compose.test.yaml ps
docker-compose -f docker-compose.test.yaml down
```

#### Détection Automatique Environnement

Le fichier `conftest.py` détecte automatiquement l'environnement (local vs CI):

```python
# conftest.py
import os

# Détection automatique de l'environnement
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"

# Ports adaptatifs selon l'environnement
TEST_PORTS = {
    "postgres": 5432 if IS_GITHUB_ACTIONS else 5433,  # CI: 5432, Local: 5433
    "redis": 6379 if IS_GITHUB_ACTIONS else 6380,      # CI: 6379, Local: 6380
}

# Configuration des connexions de test
TEST_DATABASE_URL = (
    f"postgresql+asyncpg://core-africare-identity_test:test_password@localhost:"
    f"{TEST_PORTS['postgres']}/core-africare-identity_test"
)

TEST_REDIS_URL = f"redis://localhost:{TEST_PORTS['redis']}/0"
```

**Avantages:**
- ✅ Même code de test en local et en CI
- ✅ Pas de configuration manuelle selon l'environnement
- ✅ Services GitHub Actions utilisent ports standard (5432, 6379)
- ✅ Services locaux utilisent ports exotiques (5433, 6380)

#### Fixtures avec Auto-Cleanup

**Fixture Database (auto-rollback):**
```python
@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Fournit une session de test avec rollback automatique."""
    session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    async with session_maker() as session:
        yield session
        await session.rollback()  # Auto-cleanup après chaque test
```

**Fixture Redis (auto-flushdb):**
```python
@pytest.fixture
async def redis_client(test_redis_client):
    """Fournit un client Redis avec nettoyage automatique."""
    yield test_redis_client
    await test_redis_client.flushdb()  # Auto-cleanup après chaque test
```

**Bénéfices:**
- ✅ Isolation complète entre tests
- ✅ Pas de pollution de données
- ✅ Pas besoin de cleanup manuel dans les tests

#### Structure des Tests d'Intégration

```
tests/
├── integration/                   # Tests d'intégration
│   ├── __init__.py
│   ├── test_database_integration.py   # 8 tests PostgreSQL
│   └── test_redis_integration.py      # 12 tests Redis
├── unit/                          # Tests unitaires (mocks)
│   └── ...
└── conftest.py                    # Fixtures partagées
```

**Marqueurs pytest:**
```python
@pytest.mark.integration   # Marque les tests d'intégration
@pytest.mark.asyncio       # Tests async
```

#### Commandes de Test

**Tests d'intégration:**
```bash
# Tous les tests d'intégration (avec services)
make test-integration
# → Exécute: pytest tests/ -v -m integration --cov=app

# Tests d'intégration spécifiques
make test-services-up  # Démarrer les services d'abord
poetry run pytest tests/integration/test_database_integration.py -v
poetry run pytest tests/integration/test_redis_integration.py -v
make test-services-down
```

**Tests unitaires (sans services externes):**
```bash
# Tests unitaires uniquement (mocks)
make test-unit
# → Exécute: pytest tests/ -v -m "not integration" --cov=app
```

**Tous les tests:**
```bash
# Tous les tests (unit + integration)
make test-all
# → Démarre services, exécute tous tests, arrête services
# → Génère rapport de couverture HTML dans htmlcov/

# Tests avec couverture détaillée
pytest --cov=app --cov-report=html --cov-report=term-missing
```

#### Exemples de Tests d'Intégration

**Test Database (PostgreSQL):**
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_and_read_patient(db_session: AsyncSession):
    """Test création et lecture d'un patient avec PostgreSQL réel."""
    patient = Patient(
        keycloak_user_id="test-user-123",
        first_name="Amadou",
        last_name="Diallo",
        date_of_birth=date(1990, 5, 15),
        gender="male",
        email="amadou.diallo@example.sn",
        phone="+221771234567",
        country="Sénégal",
        preferred_language="fr",
        is_active=True,
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    # Vérifications
    assert patient.id is not None
    assert patient.created_at is not None
    assert patient.email == "amadou.diallo@example.sn"
```

**Test Redis (cache et pub/sub):**
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_set_and_get(redis_client):
    """Test opérations de base Redis."""
    await redis_client.set("test_key", "test_value", ex=60)
    value = await redis_client.get("test_key")
    assert value == "test_value"

@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_pubsub(redis_client):
    """Test publication/souscription Redis."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("test_channel")

    # Publier un message
    await redis_client.publish("test_channel", "Hello Redis!")

    # Recevoir le message
    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
    assert message["data"] == "Hello Redis!"
```

#### Configuration CI/CD

**GitHub Actions (`.github/workflows/ci.yaml`):**
```yaml
services:
  postgres:
    image: postgres:18
    env:
      POSTGRES_USER: core-africare-identity_test
      POSTGRES_PASSWORD: test_password
      POSTGRES_DB: core-africare-identity_test
    ports:
      - 5432:5432  # Port standard en CI
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5

  redis:
    image: redis:7-alpine
    ports:
      - 6379:6379  # Port standard en CI
    options: >-
      --health-cmd "redis-cli ping"
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5

steps:
  - name: Exécution des tests avec coverage
    env:
      SQLALCHEMY_DATABASE_URI: postgresql+asyncpg://core-africare-identity_test:test_password@localhost:5432/core-africare-identity_test
      REDIS_URL: redis://localhost:6379/0
    run: poetry run pytest --cov=app --cov-report=xml
```

#### Bonnes Pratiques

**1. Isolation des Tests:**
- Chaque test doit être **indépendant**
- Utiliser fixtures avec auto-cleanup
- Ne pas partager d'état entre tests

**2. Nommage:**
```python
# ✅ Bon - Nom descriptif
async def test_create_patient_with_valid_data_creates_record_in_database()

# ❌ Mauvais - Nom vague
async def test_patient()
```

**3. Assertions Claires:**
```python
# ✅ Bon - Assertions spécifiques
assert patient.email == "expected@example.com"
assert patient.is_active is True
assert patient.created_at <= datetime.now(UTC)

# ❌ Mauvais - Assertion générique
assert patient is not None
```

**4. Timeout pour Tests Async:**
```python
# Éviter les tests qui bloquent indéfiniment
@pytest.mark.timeout(30)  # 30 secondes max
@pytest.mark.asyncio
async def test_long_running_operation():
    result = await slow_operation()
    assert result is not None
```

**5. Cleanup Explicite si Nécessaire:**
```python
@pytest.mark.asyncio
async def test_with_manual_cleanup(redis_client):
    """Test avec cleanup manuel si auto-cleanup insuffisant."""
    try:
        # Test logic
        await redis_client.set("temp_key", "value")
        # Assertions...
    finally:
        # Cleanup explicite
        await redis_client.delete("temp_key")
```

## OpenTelemetry Integration

### Automatic Instrumentation

The service includes **auto-instrumentation** for:
- FastAPI requests/responses
- SQLAlchemy database operations
- HTTP client calls
- Azure Event Hub operations

### Custom Telemetry

```python
from opentelemetry import trace
from opentelemetry.metrics import get_meter

tracer = trace.get_tracer(__name__)
meter = get_meter(__name__)

# Custom span
with tracer.start_as_current_span("custom_operation") as span:
    span.set_attribute("operation.type", "business_logic")
    result = await do_something()
    span.add_event("Operation completed")

# Custom metric
request_counter = meter.create_counter(
    "requests_total",
    description="Total requests processed"
)
request_counter.add(1, {"endpoint": "/examples"})
```

## Development Guidelines

### Code Patterns

**Follow these patterns when developing:**

1. **Async by default**: All I/O operations should be async
2. **Type hints**: Complete type annotations for all functions
3. **Pydantic models**: Use for all input/output validation
   - Use `typing.Literal[]` for fields with fixed value sets
   - Use `typing.Annotated[]` for reusable validations (centralize in `app/schemas/utils.py`)
4. **Error handling**: Early returns and guard clauses
5. **Pure functions**: Prefer functional over class-based approaches
6. **Event-driven**: Publish events for significant business operations
7. **Temporal data integrity**:
   - Always use `DateTime(timezone=True)` in SQLAlchemy models
   - Use PostgreSQL 18 temporal constraints (EXCLUDE USING gist) for time-based business rules
   - Extension `btree_gist` is automatically created in `init-db.sql`

### Event Naming Convention

```python
# Pattern: {service_slug}.{entity}.{action}
await publish("identity.user.created", payload)
await publish("identity.order.completed", payload)
await publish("identity.payment.failed", payload)
```

### Error Handling

```python
from fastapi import HTTPException
from opentelemetry import trace

@router.post("/examples")
async def create_example_endpoint(example: ExampleCreate):
    span = trace.get_current_span()

    try:
        # Validate input early
        if not example.name.strip():
            raise HTTPException(status_code=400, detail="Name is required")

        # Business logic
        result = await create_example(example.name)

        # Success telemetry
        span.set_attribute("example.id", str(result.id))
        return result

    except Exception as e:
        # Error telemetry
        span.record_exception(e)
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
        raise
```

### RGPD Audit Logging

**Pattern DRY avec `verify_access()` retournant les données d'audit complètes:**

La méthode `User.verify_access()` retourne maintenant un dictionnaire avec **toutes les données d'audit RGPD** nécessaires, évitant la répétition de code et garantissant la cohérence.

```python
from datetime import datetime, UTC
from app.core.events import publish

@router.get("/{patient_id}")
async def get_patient(
    patient_id: int,
    request: Request,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> PatientResponse:
    """Récupère un patient avec audit RGPD complet."""
    patient = await patient_service.get_patient(db=db, patient_id=patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient non trouvé")

    # Vérification RGPD + récupération des données d'audit
    audit_data = current_user.verify_access(patient.keycloak_user_id)
    # ✅ audit_data contient: access_reason, accessed_by (UUID uniquement, minimisation RGPD)

    # Audit RGPD complet avec spread operator (EN DERNIER)
    await publish("audit.access", {
        "event_type": "patient_record_accessed",
        "resource_type": "patient",
        "resource_id": patient.id,
        "resource_owner_id": patient.keycloak_user_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "ip_address": request.client.host,
        "user_agent": request.headers.get("user-agent"),
        **audit_data,  # ⚠️ IMPORTANT: En dernier pour ne pas écraser les champs event-specific
    })

    return PatientResponse.model_validate(patient)
```

**Contenu de `audit_data` (retourné par `verify_access()`):**

| Champ | Purpose | Exemple |
|-------|---------|---------|
| `access_reason` | Catégorie d'accès (validation légale) | `"owner"` ou `"admin_supervision"` |
| `accessed_by` | UUID Keycloak (traçabilité, identifiant technique) | `"550e8400-e29b-41d4-a716-446655440000"` |

**Note RGPD - Principe de minimisation des données:**
Seul l'UUID Keycloak est inclus dans les logs d'audit. Les noms, usernames et emails sont EXCLUS pour respecter le principe de minimisation (Article 5.1.c du RGPD). L'UUID suffit pour la traçabilité technique.

**Avantages du pattern DRY:**

1. **`verify_access()`** retourne TOUT en un seul appel
   - Plus de répétition de `current_user.sub`, `current_user.email`, etc.
   - Cohérence garantie des données d'audit

2. **Spread operator (`**audit_data`)** simplifie le code
   - Toutes les clés d'audit injectées automatiquement
   - ⚠️ **IMPORTANT**: Placer `**audit_data` EN DERNIER pour éviter d'écraser les champs event-specific
   - Code plus lisible et maintenable

3. **Compliance RGPD automatique**
   - Impossible d'oublier `accessed_by` ou `access_reason`
   - Pattern uniforme à travers tous les endpoints

**Implémentation de `verify_access()` dans `app/core/security.py`:**

```python
def verify_access(self, resource_owner_id: str) -> dict:
    """
    Vérifie l'accès et retourne les données d'audit RGPD (minimisation des données).

    Returns:
        dict avec:
        - access_reason: "owner" ou "admin_supervision"
        - accessed_by: UUID Keycloak de l'accédant (identifiant technique uniquement)

    Raises:
        HTTPException 403 si ni owner ni admin

    Note RGPD: Seul l'UUID Keycloak est inclus (principe de minimisation).
               Les noms/emails/usernames sont exclus des logs d'audit.
    """
    if self.is_owner(resource_owner_id):
        return {"access_reason": "owner", "accessed_by": self.sub}

    if self.is_admin:
        return {"access_reason": "admin_supervision", "accessed_by": self.sub}

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Accès refusé : vous devez être le propriétaire de la ressource",
    )
```

## Environment Variables Management

### Configuration Files Structure

Le service utilise une approche multi-fichiers pour la gestion des variables d'environnement:

```
core-africare-identity/
├── .env.example          # Template complet avec documentation
├── .env.development      # Configuration pour développement local
├── .env                  # Configuration active (git-ignored, créé depuis .env.example)
├── app/core/config.py    # Définition Pydantic des variables
├── docker-compose.yaml   # Variables pour conteneurs Docker
└── .github/
    ├── scripts/
    │   └── setup-secrets.sh    # Automatisation secrets GitHub
    └── workflows/
        ├── ci.yaml       # Variables pour tests CI
        └── cd.yaml       # Variables pour déploiement CD
```

### Fichiers de Configuration

**1. `.env.example` - Template Documentation**
- Contient TOUTES les variables avec descriptions
- Valeurs par défaut ou placeholders
- Ne contient jamais de secrets réels
- Commité dans Git
- À copier en `.env` pour usage local

**2. `.env.development` - Configuration Locale**
- Valeurs pré-remplies pour développement
- Connection strings localhost
- Debug activé, CORS permissif
- OpenTelemetry en mode console
- Peut être commité (pas de secrets de production)

**3. `.env` - Configuration Active**
- Créé depuis `.env.example` ou `.env.development`
- Contient les valeurs réelles (peut inclure secrets)
- **JAMAIS commité** (dans .gitignore)
- Utilisé par `docker-compose` et développement local

**4. `app/core/config.py` - Validation Pydantic**
- Définit le schéma de toutes les variables
- Validation de type automatique
- Computed fields et helpers
- Source unique de vérité pour les settings

**5. `docker-compose.yaml` - Variables Conteneurs**
- Variables d'environnement pour les services Docker
- Utilise les valeurs de cookiecutter pour génération
- Synchronisé avec `app/core/config.py`

### GitHub Actions - Secrets et Variables

**Configuration Automatisée:**

```bash
# 1. Copier et modifier le fichier .env pour l'environnement cible
cp .env.example .env.production
vim .env.production

# 2. Exécuter le script de configuration
./.github/scripts/setup-secrets.sh production

# 3. Vérifier la configuration
gh secret list --env production
gh variable list --env production
```

**Configuration Manuelle:**

```bash
# Secrets (valeurs sensibles)
gh secret set KEYCLOAK_CLIENT_SECRET --env production --body "secret-value"
gh secret set SQLALCHEMY_DATABASE_URI --env production --body "postgresql+asyncpg://..."
# Variables (valeurs publiques)
gh variable set AZURE_EVENTHUB_NAMESPACE --env production --body "africare.servicebus.windows.net"
gh variable set OTEL_SERVICE_NAME --env production --body "core-africare-identity"
```

**Environnements GitHub:**
- `development` - Développement continu
- `staging` - Tests pré-production
- `production` - Production (avec protection et reviewers)

### Synchronisation des Variables

**Sources de vérité par ordre de priorité:**

1. **`app/core/config.py`** - Définition Pydantic (schéma, types, validation)
2. **`.env.example`** - Documentation complète (noms, descriptions, exemples)
3. **`docker-compose.yaml`** - Variables pour conteneurs Docker
4. **`.github/workflows/*.yaml`** - Variables pour CI/CD
5. **`.github/scripts/setup-secrets.sh`** - Automation GitHub secrets

**Processus d'ajout d'une nouvelle variable:**

1. Ajouter dans `app/core/config.py`:
   ```python
   class Settings(BaseSettings):
       # Nouvelle variable
       NEW_VARIABLE: str
   ```

2. Documenter dans `.env.example`:
   ```bash
   # Description de la nouvelle variable
   NEW_VARIABLE=valeur-exemple
   ```

3. Ajouter valeur par défaut dans `.env.development`:
   ```bash
   NEW_VARIABLE=valeur-dev
   ```

4. Synchroniser dans `docker-compose.yaml`:
   ```yaml
   environment:
     NEW_VARIABLE: {{cookiecutter.new_variable}}
   ```

5. Ajouter dans `.github/scripts/setup-secrets.sh`:
   ```bash
   # Si secret
   set_secret "NEW_VARIABLE" "${NEW_VARIABLE:-}" "$ENVIRONMENT"
   # Si variable publique
   set_variable "NEW_VARIABLE" "${NEW_VARIABLE:-}" "$ENVIRONMENT"
   ```

6. Ajouter dans workflows si nécessaire (`.github/workflows/ci.yaml`, `cd.yaml`)

### Bonnes Pratiques

**1. Secrets vs Variables:**
- **Secrets** (chiffrés, masqués dans logs): passwords, tokens, connection strings complètes
- **Variables** (publiques, visibles): namespaces, URLs publiques, noms de services

**2. Hiérarchie de Configuration:**
```
Secrets GitHub (production) > Variables GitHub > .env > .env.development > .env.example
```

**3. Ne jamais committer:**
- `.env` (fichier actif avec valeurs réelles)
- Fichiers contenant secrets de production
- Connection strings réelles

**4. Toujours committer:**
- `.env.example` (template documentation)
- `.env.development` (valeurs localhost, pas de secrets prod)
- `app/core/config.py` (schéma Pydantic)

**5. Validation:**
```bash
# Vérifier que toutes les variables requises sont définies
poetry run python -c "from app.core.config import settings; print('OK')"

# Tester le chargement des variables
make run  # Doit démarrer sans erreur
```

## CI/CD avec GitHub Actions

### Workflows Disponibles

Le template génère automatiquement 2 workflows GitHub Actions:

**1. CI Workflow (`.github/workflows/ci.yaml`)**
- Déclenchement: Push, Pull Request, manuel
- Jobs: Linting (Ruff), Tests (pytest + coverage), Docker build, Security scan
- Variables: Toutes définies dans le workflow pour isolation des tests

**2. CD Workflow (`.github/workflows/cd.yaml`)**
- Déclenchement: Push sur `main`/`develop`, ou manuel avec choix d'environnement
- Jobs: Build Docker image, Push vers GHCR, Déploiement Azure Container Apps
- Environnements: development, staging, production

### Configuration Initiale

**1. Créer les Environnements GitHub:**

Via l'interface web: `Settings > Environments > New environment`

```
- development  (pas de protection)
- staging      (limiter aux branches develop, main)
- production   (reviewers requis, limiter à main)
```

**2. Configurer les Secrets et Variables:**

```bash
# Option automatique (recommandée)
./.github/scripts/setup-secrets.sh production

# Option manuelle via gh CLI
gh secret set KEYCLOAK_CLIENT_SECRET --env production --body "..."
gh variable set OTEL_SERVICE_NAME --env production --body "core-africare-identity"

# Vérification
gh secret list --env production
gh variable list --env production
```

**3. Configurer Azure Credentials:**

```bash
# Créer un Service Principal Azure
az ad sp create-for-rbac \
  --name "sp-core-africare-identity-github" \
  --role contributor \
  --scopes /subscriptions/{sub-id}/resourceGroups/rg-africare-production \
  --sdk-auth

# Ajouter comme secret
gh secret set AZURE_CREDENTIALS --env production --body '{...json...}'
```

### Utilisation des Workflows

**Déclenchement Automatique:**
```bash
# Push sur develop → déploiement staging
git push origin develop

# Push sur main → déploiement production (après review)
git push origin main
```

**Déclenchement Manuel:**
```bash
# Via gh CLI
gh workflow run cd.yaml -f environment=staging

# Via interface web
https://github.com/btall/core-africare-identity/actions/workflows/cd.yaml
```

**Surveillance:**
```bash
# Lister les exécutions
gh run list

# Voir les logs
gh run view {run-id} --log

# Suivre en temps réel
gh run watch
```

### Secrets et Variables Requis

**Secrets (par environnement):**
| Secret | Description |
|--------|-------------|
| `KEYCLOAK_CLIENT_SECRET` | Client secret Keycloak |
| `SQLALCHEMY_DATABASE_URI` | URL PostgreSQL complète |
| `AZURE_EVENTHUB_CONNECTION_STRING` | Event Hub connection (fallback) |
| `AZURE_CREDENTIALS` | Service principal Azure (JSON) |

**Variables (par environnement):**
| Variable | Exemple |
|----------|---------|
| `AZURE_EVENTHUB_NAMESPACE` | `africare.servicebus.windows.net` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `https://otel.africare.sn` |
| `ALLOWED_ORIGINS` | `https://app.africare.sn` |

Documentation complète: `.github/README.md`

## Deployment Considerations

### Environment Setup

- **Development**: Uses `docker-compose.yaml` with complete local stack
  - PostgreSQL 18 container with automatic initialization via `init-db.sql`
  - Volume persistence for database data
  - Application service with all dependencies configured
  - Automatic restart and hot-reload during development
- **Staging/Production**: Requires external resources
  - PostgreSQL Flexible Server (Azure) or equivalent
  - Azure Event Hub namespace
  - OpenTelemetry Collector
- **Health Checks**: Available at `/api/v1/health`
- **OpenAPI Docs**: Available at `/docs` and `/redoc`

### Local Development with Docker Compose

Le fichier `docker-compose.yaml` inclut tous les services nécessaires :

```bash
# Démarrer tous les services
docker-compose up -d

# Voir les logs
docker-compose logs -f core-africare-identity

# Redémarrer le service applicatif
docker-compose restart core-africare-identity

# Arrêter tous les services
docker-compose down

# Arrêter et supprimer les volumes (réinitialisation complète)
docker-compose down -v
```

**PostgreSQL Initialization**:
Le fichier `init-db.sql` est automatiquement exécuté au premier démarrage du conteneur PostgreSQL pour créer la base de données et l'utilisateur.
### Required Infrastructure

1. **PostgreSQL 18 database**: Async-compatible (asyncpg driver)
   - Development: Docker container with volume persistence
   - Production: Azure PostgreSQL Flexible Server
2. **Azure Event Hub**: Namespace and EventHub named `core-africare-identity`
3. **Azure Blob Storage**: For Event Hub checkpoint store
4. **Keycloak**: Authentication and authorization server
5. **OpenTelemetry Collector**: For traces/metrics export (Grafana stack recommended)
6. **Environment Variables**: As documented in configuration section

This service is designed for **cloud-native deployment** with proper observability, event-driven architecture, and scalable async patterns.

---

## Conventions de Code et Git

Cette section documente les standards de code et les conventions de commits observés dans ce projet.

### Standards de Code Python

#### 1. Asynchronisme par Défaut

Toutes les opérations I/O doivent être asynchrones:

```python
# ✅ Bon
async def get_user(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

# ❌ Mauvais
def get_user(db: Session, user_id: int) -> User:
    return db.query(User).filter(User.id == user_id).first()
```

#### 2. Type Hints Complets

Annotations de type pour tous les paramètres et retours:

```python
# ✅ Bon
from typing import Optional

async def create_user(
    db: AsyncSession,
    name: str,
    email: str,
    age: Optional[int] = None
) -> User:
    user = User(name=name, email=email, age=age)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

# ❌ Mauvais
async def create_user(db, name, email, age=None):
    user = User(name=name, email=email, age=age)
    db.add(user)
    await db.commit()
    return user
```

#### 3. Pydantic pour Validation

Utiliser Pydantic pour toutes les validations d'entrée/sortie:

```python
# ✅ Bon
from pydantic import BaseModel, EmailStr, field_validator

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    age: Optional[int] = None

    @field_validator("age")
    @classmethod
    def validate_age(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > 150):
            raise ValueError("Age must be between 0 and 150")
        return v

@router.post("/users", response_model=UserResponse)
async def create_user_endpoint(user: UserCreate) -> UserResponse:
    # Validation automatique par Pydantic
    result = await create_user(user)
    return UserResponse.model_validate(result)
```

#### 4. Fonctions Pures Préférées

Privilégier les fonctions pures aux classes:

```python
# ✅ Bon - Fonction pure
async def calculate_total_price(
    items: list[Item],
    discount_percent: float = 0.0
) -> Decimal:
    subtotal = sum(item.price * item.quantity for item in items)
    discount = subtotal * Decimal(discount_percent / 100)
    return subtotal - discount

# ⚠️ Acceptable mais moins préféré
class PriceCalculator:
    def __init__(self, discount_percent: float = 0.0):
        self.discount_percent = discount_percent

    async def calculate_total(self, items: list[Item]) -> Decimal:
        # ... même logique
```

#### 5. Early Returns et Guard Clauses

Gérer les cas d'erreur tôt:

```python
# ✅ Bon
async def process_order(order_id: int) -> Order:
    order = await get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot process cancelled order")

    if order.total <= 0:
        raise HTTPException(status_code=400, detail="Invalid order total")

    # Logique principale ici
    await process_payment(order)
    await update_inventory(order)
    return order

# ❌ Mauvais - Nesting profond
async def process_order(order_id: int) -> Order:
    order = await get_order(order_id)
    if order:
        if order.status != "cancelled":
            if order.total > 0:
                await process_payment(order)
                await update_inventory(order)
                return order
            else:
                raise HTTPException(...)
        else:
            raise HTTPException(...)
    else:
        raise HTTPException(...)
```

#### 6. OpenTelemetry Intégré

Instrumenter le code critique:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def process_payment(order: Order) -> Payment:
    with tracer.start_as_current_span("process_payment") as span:
        span.set_attribute("order.id", str(order.id))
        span.set_attribute("order.total", float(order.total))

        try:
            payment = await charge_payment_gateway(order)
            span.set_attribute("payment.status", "success")
            span.add_event("Payment processed successfully")
            return payment
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise
```

#### 7. Gestion d'Erreurs avec RFC 9457

Utiliser des réponses d'erreur standardisées (RFC 9457 - Problem Details for HTTP APIs):

```python
from fastapi import HTTPException

@router.post("/orders")
async def create_order(order: OrderCreate) -> OrderResponse:
    try:
        # Validation métier
        if not order.items:
            raise HTTPException(
                status_code=400,
                detail="Order must contain at least one item"
            )

        result = await create_order_service(order)
        return OrderResponse.model_validate(result)

    except Exception as e:
        span = trace.get_current_span()
        span.record_exception(e)
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
        raise
```

#### 8. Utilisation de `typing.Literal[]` pour les Enums

Toujours utiliser `typing.Literal[]` pour restreindre un champ à un ensemble fixe de valeurs:

```python
# ✅ Bon - Literal pour valeurs fixes
from typing import Literal
from pydantic import BaseModel

class PatientRecord(BaseModel):
    status: Literal["draft", "active", "completed", "cancelled"]
    priority: Literal["low", "medium", "high", "urgent"]
    gender: Literal["male", "female", "other", "unknown"]

# ❌ Mauvais - String sans restriction
class PatientRecord(BaseModel):
    status: str  # Accepte n'importe quelle chaîne
    priority: str
    gender: str

# ❌ Éviter - Enum classique (moins pratique avec Pydantic)
from enum import Enum

class Status(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PatientRecord(BaseModel):
    status: Status  # Fonctionne mais Literal est préféré
```

**Avantages de `Literal`:**
- Validation automatique par Pydantic
- Documentation claire dans OpenAPI/Swagger
- Auto-complétion dans les IDE
- Erreurs de validation explicites
- Sérialisation/désérialisation simple (pas de conversion Enum)

#### 9. Temporal Constraints PostgreSQL 18+ (WITHOUT OVERLAPS)

Utiliser les **temporal constraints native de PostgreSQL 18+** avec la clause `WITHOUT OVERLAPS` pour garantir l'intégrité des données basées sur le temps:

**Configuration requise** (automatique dans `init-db.sql`):
```sql
-- Extension btree_gist pour les temporal constraints
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

**Fonctionnalité PostgreSQL 18 Native:**

PostgreSQL 18 introduit la clause **`WITHOUT OVERLAPS`** qui permet de définir des contraintes temporelles directement dans les PRIMARY KEY et UNIQUE constraints, sans utiliser EXCLUDE USING gist.

**Exemple 1: Employés avec périodes de validité (pas de chevauchement)**

```sql
-- Schéma SQL natif PostgreSQL 18
CREATE TABLE employees (
    emp_id INTEGER,
    emp_name VARCHAR(100) NOT NULL,
    valid_period tstzrange NOT NULL,
    PRIMARY KEY (emp_id, valid_period WITHOUT OVERLAPS)
);

-- Exemples d'insertions
INSERT INTO employees VALUES
    (1, 'Alice', tstzrange('2024-01-01', '2024-06-30')),
    (1, 'Alice', tstzrange('2024-07-01', '2024-12-31'));  -- OK: pas de chevauchement

-- Cette insertion échouera (chevauchement détecté)
INSERT INTO employees VALUES
    (1, 'Alice', tstzrange('2024-06-15', '2024-08-15'));  -- ERROR: période chevauche!
```

**Exemple 2: Rendez-vous médicaux (SQLAlchemy + Alembic)**

```python
# app/models/appointment.py
from datetime import datetime
from typing import Literal
from sqlalchemy import String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import TSTZRANGE
from app.core.database import Base

class Appointment(Base):
    """Rendez-vous avec contraintes temporelles PostgreSQL 18."""
    __tablename__ = "appointments"

    practitioner_id: Mapped[int]
    patient_id: Mapped[int]
    appointment_period: Mapped[TSTZRANGE] = mapped_column(TSTZRANGE, nullable=False)
    status: Mapped[Literal["scheduled", "completed", "cancelled"]]

    # Note: PRIMARY KEY avec WITHOUT OVERLAPS doit être défini en SQL raw (Alembic)
```

**Migration Alembic avec WITHOUT OVERLAPS:**

```python
# alembic/versions/xxx_add_temporal_appointments.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    # Créer la table avec colonnes de base
    op.create_table(
        'appointments',
        sa.Column('practitioner_id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('appointment_period', postgresql.TSTZRANGE(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False)
    )

    # Ajouter PRIMARY KEY avec WITHOUT OVERLAPS (PostgreSQL 18 natif)
    op.execute("""
        ALTER TABLE appointments
        ADD PRIMARY KEY (practitioner_id, appointment_period WITHOUT OVERLAPS)
    """)

def downgrade():
    op.drop_table('appointments')
```

**Exemple 3: Tarification avec périodes de validité**

```sql
CREATE TABLE pricing (
    product_id INTEGER,
    price DECIMAL(10,2) NOT NULL,
    valid_period daterange NOT NULL,
    UNIQUE (product_id, valid_period WITHOUT OVERLAPS)
);

-- Insertion de différentes périodes de prix
INSERT INTO pricing VALUES
    (100, 29.99, daterange('2024-01-01', '2024-03-31')),
    (100, 34.99, daterange('2024-04-01', '2024-06-30'));

-- Requête: quel prix à une date donnée?
SELECT price
FROM pricing
WHERE product_id = 100
  AND valid_period @> '2024-05-15'::date;
```

**Cas d'usage courants:**

1. **Rendez-vous sans chevauchement (praticien occupé)**
   ```sql
   PRIMARY KEY (practitioner_id, appointment_period WITHOUT OVERLAPS)
   ```

2. **Historique salarial (un seul salaire actif à la fois)**
   ```sql
   CREATE TABLE employee_salaries (
       employee_id INTEGER,
       salary DECIMAL(10,2),
       effective_period tstzrange,
       PRIMARY KEY (employee_id, effective_period WITHOUT OVERLAPS)
   );
   ```

3. **Réservations de ressources (salle, équipement)**
   ```sql
   CREATE TABLE room_reservations (
       room_id INTEGER,
       reserved_by VARCHAR(100),
       reservation_period tstzrange,
       UNIQUE (room_id, reservation_period WITHOUT OVERLAPS)
   );
   ```

4. **Versions de configuration avec validité temporelle**
   ```sql
   CREATE TABLE config_versions (
       config_key VARCHAR(50),
       config_value JSONB,
       valid_period tstzrange,
       PRIMARY KEY (config_key, valid_period WITHOUT OVERLAPS)
   );
   ```

**Avantages de WITHOUT OVERLAPS (vs EXCLUDE USING gist):**

- **Syntaxe native** : Plus simple et lisible que EXCLUDE USING gist
- **Performance** : Optimisé par PostgreSQL pour les requêtes temporelles
- **Intégration PRIMARY KEY/UNIQUE** : S'intègre naturellement aux contraintes standard
- **Point-in-time queries** : Support natif de `@>` (containment operator)
- **Maintenance** : Moins de complexité qu'avec des contraintes d'exclusion manuelles

**Requêtes temporelles courantes:**

```sql
-- Trouver rendez-vous actifs à un moment précis
SELECT * FROM appointments
WHERE appointment_period @> '2024-06-15 14:30:00'::timestamptz;

-- Trouver tous les rendez-vous dans une plage
SELECT * FROM appointments
WHERE appointment_period && tstzrange('2024-06-01', '2024-06-30');

-- Vérifier si une période est disponible
SELECT NOT EXISTS (
    SELECT 1 FROM appointments
    WHERE practitioner_id = 5
      AND appointment_period && tstzrange('2024-06-15 10:00', '2024-06-15 11:00')
) AS is_available;
```

#### 10. Gestion des TimeZones avec SQLAlchemy

**TOUJOURS** utiliser `DateTime(timezone=True)` pour les champs temporels:

```python
# ✅ Bon - Avec timezone
from datetime import datetime, UTC
from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str]
    # Toujours avec timezone=True
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

# ❌ Mauvais - Sans timezone
class AuditLog(Base):
    created_at: Mapped[datetime] = mapped_column(DateTime())  # Timezone naive!
```

**Utilisation avec Pydantic:**

```python
from datetime import datetime, UTC
from pydantic import BaseModel, Field

class AuditLogCreate(BaseModel):
    event_type: str
    # Pydantic valide automatiquement les datetime timezone-aware
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

class AuditLogResponse(BaseModel):
    id: int
    event_type: str
    created_at: datetime  # Automatiquement timezone-aware depuis PostgreSQL
    updated_at: datetime

    class Config:
        from_attributes = True
```

**Bonnes pratiques:**

```python
# ✅ Toujours utiliser UTC pour le stockage
from datetime import datetime, UTC

# Création
now = datetime.now(UTC)

# Comparaison
if event.created_at > datetime.now(UTC):
    # ...

# Formatage pour API
event.created_at.isoformat()  # '2025-01-15T10:30:00+00:00'
```

#### 11. `typing.Annotated[]` et Centralisation des Schémas

Préférer `typing.Annotated[]` pour les validations Pydantic réutilisables (quand `fastapi.Depends()` n'est pas nécessaire):

**Créer `app/schemas/utils.py` pour centraliser les annotations:**

```python
# app/schemas/utils.py
"""Annotations Pydantic réutilisables pour validation."""

from typing import Annotated
from pydantic import Field, EmailStr, StringConstraints

# Types de base avec validation
PositiveInt = Annotated[int, Field(gt=0, description="Entier positif")]
NonNegativeInt = Annotated[int, Field(ge=0, description="Entier non-négatif")]
PositiveFloat = Annotated[float, Field(gt=0.0, description="Flottant positif")]

# Chaînes avec contraintes
NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
PhoneNumber = Annotated[str, StringConstraints(pattern=r'^\+?[1-9]\d{1,14}$')]
PostalCode = Annotated[str, StringConstraints(pattern=r'^\d{5}$')]

# Identifiants
PatientId = Annotated[int, Field(gt=0, description="ID unique du patient")]
PractitionerId = Annotated[int, Field(gt=0, description="ID unique du praticien")]
AppointmentId = Annotated[int, Field(gt=0, description="ID unique du rendez-vous")]

# Métadonnées
Email = Annotated[EmailStr, Field(description="Adresse email valide")]
Description = Annotated[str, Field(max_length=1000, description="Description texte")]
Title = Annotated[str, Field(min_length=1, max_length=255, description="Titre")]

# Plages de valeurs
AgeYears = Annotated[int, Field(ge=0, le=150, description="Âge en années")]
Percentage = Annotated[float, Field(ge=0.0, le=100.0, description="Pourcentage 0-100")]
```

**Utilisation dans les modèles Pydantic:**

```python
# app/schemas/patient.py
from typing import Optional
from pydantic import BaseModel
from app.schemas.utils import (
    PatientId,
    Email,
    NonEmptyStr,
    PhoneNumber,
    AgeYears,
    Description
)

class PatientBase(BaseModel):
    name: NonEmptyStr
    email: Email
    phone: Optional[PhoneNumber] = None
    age: Optional[AgeYears] = None

class PatientCreate(PatientBase):
    medical_history: Optional[Description] = None

class PatientResponse(PatientBase):
    id: PatientId
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

**Avantages de cette approche:**

1. **Réutilisabilité** - Définir une fois, utiliser partout
2. **Cohérence** - Validation uniforme à travers tous les modèles
3. **Documentation** - Descriptions centralisées et claires
4. **Maintenabilité** - Modifier une seule définition met à jour tous les usages
5. **Type safety** - IDE auto-completion et vérification de types

**Quand utiliser `Annotated[]` vs `Depends()`:**

```python
from fastapi import Depends
from typing import Annotated

# ✅ Bon - Annotated pour validation de données
def create_patient(
    patient: PatientCreate,  # Utilise Annotated dans le schéma
    db: Annotated[AsyncSession, Depends(get_session)]  # Depends pour injection
):
    pass

# ❌ Mauvais - Depends pour validation simple
def create_patient(
    name: Annotated[str, Depends(lambda: Field(min_length=1))]  # Inutile!
):
    pass
```

### Conventions Git

#### Format Conventional Commits (Français)

**Structure:**
```
<type>(<scope>): <titre court en français>

<description détaillée en français avec sections>

<sections optionnelles>
```

**Types de Commits:**

- **feat**: Nouvelle fonctionnalité
  ```
  feat(auth): ajout de l'authentification multi-facteurs (MFA)
  ```

- **fix**: Correction de bug
  ```
  fix(database): correction de la fuite mémoire dans les connexions PostgreSQL
  ```

- **refactor**: Refactorisation sans changement fonctionnel
  ```
  refactor(events): simplification du système de retry avec backoff exponentiel
  ```

- **docs**: Modification de documentation
  ```
  docs(api): mise à jour de la documentation OpenAPI avec exemples
  ```

- **chore**: Tâches de maintenance
  ```
  chore(deps): mise à jour des dépendances vers les dernières versions
  ```

- **test**: Ajout ou modification de tests
  ```
  test(services): ajout de tests unitaires pour le service de paiement
  ```

- **perf**: Amélioration de performance
  ```
  perf(cache): implémentation du cache Redis pour les requêtes fréquentes
  ```

#### Structure des Messages Détaillés

Les commits significatifs doivent inclure une description détaillée structurée:

```
refactor(events): implémentation du checkpoint store pour Azure Event Hub

CONTEXTE :

Après analyse du déploiement de 21 microservices AfriCare, identification
d'un problème critique : absence de checkpoint store causant le retraitement
complet des événements à chaque redémarrage.

PROBLÈME IDENTIFIÉ :

1. Sans BlobCheckpointStore, tous les événements sont relus depuis le début
   - Cause : retraitement massif, doublons, surcharge au démarrage
   - Impact : catastrophique en production avec volume élevé

2. Inefficacité des connexions
   - Création d'un nouveau client à chaque publish()
   - Impact : latence élevée et gaspillage de ressources

SOLUTION IMPLÉMENTÉE :

1. Checkpoint Store avec Azure Blob Storage
   - Ajout de BlobCheckpointStore dans create_consumer_client()
   - Checkpoints automatiquement sauvegardés après traitement
   - Reprise exacte après redémarrage

2. Réutilisation du Producer Client
   - Client créé UNE FOIS au démarrage (lifespan)
   - Réutilisation pour toutes les publications
   - Fermeture propre au shutdown

Modifications:
- app/core/events.py: Implémentation checkpoint store et retry
- docs/events.md: Documentation complète des changements

Avantages:
- Fiabilité: Aucun événement perdu ou retraité indûment
- Performance: Réduction latence et charge CPU
- Scalabilité: Scale horizontal possible avec consumer groups

Breaking changes: AUCUN
Rétro-compatibilité: COMPLÈTE

Fichiers modifiés:
- core-africare-identity/app/core/events.py
- core-africare-identity/docs/events.md
```

#### Sections Recommandées pour Commits Détaillés

**Pour les features majeures:**
- CONTEXTE/MOTIVATION
- PROBLÈME IDENTIFIÉ
- SOLUTION IMPLÉMENTÉE
- MODIFICATIONS DÉTAILLÉES (avec code snippets si pertinent)
- AVANTAGES/BÉNÉFICES
- BREAKING CHANGES (ou AUCUN)
- RÉTRO-COMPATIBILITÉ
- FICHIERS MODIFIÉS

**Pour les refactorings:**
- MOTIVATION
- DÉCISIONS DE CONCEPTION CLÉS
- POINTS SAILLANTS DE L'IMPLÉMENTATION
- BÉNÉFICES
- NOTES TECHNIQUES
- FICHIERS MODIFIÉS

**Pour les fixes:**
- PROBLÈME
- CAUSE RACINE
- SOLUTION
- TESTS EFFECTUÉS
- FICHIERS MODIFIÉS

#### Bonnes Pratiques Git

1. **Commits Atomiques**
   - Un commit = une modification logique
   - Possibilité de revert sans casser d'autres fonctionnalités

2. **Messages Descriptifs**
   - Titre clair (50 caractères max)
   - Description détaillée pour commits significatifs
   - Code snippets en Markdown pour clarté

3. **Commits Fréquents**
   - Commit après chaque unité de travail complète
   - Push régulier vers la branche

4. **Branches Descriptives**
   ```bash
   # ✅ Bon
   feat/multi-eventhub-consumption
   fix/docker-compose-config-sync
   refactor/simplify-role-based-access-control

   # ❌ Mauvais
   my-branch
   temp
   fix-stuff
   ```

5. **Commit & Push Atomique**
   ```bash
   # Méthode recommandée
   git add -A && git commit -m "message détaillé" && git push origin $(git branch --show-current)
   ```

6. **Validation Markdown des Messages de Commit**

   Les messages de commit détaillés doivent être compatibles Markdown et validés avant commit.

   **Workflow recommandé pour commits détaillés:**

   ```bash
   # 1. Générer un identifiant aléatoire
   COMMIT_ID=$(shuf -i 1000-9999 -n 1)

   # 2. Écrire le message dans un fichier temporaire
   cat > /tmp/commit_message_${COMMIT_ID}.md <<'EOF'
   refactor(events): implémentation du checkpoint store pour Azure Event Hub

   CONTEXTE :

   Après analyse du déploiement de 21 microservices AfriCare...

   ## Section avec Markdown

   - Point 1
   - Point 2

   **Code snippet:**
   ```python
   async def example():
       pass
   ```

   FICHIERS MODIFIÉS :

   - app/core/events.py
   - docs/events.md
   EOF

   # 3. Valider le Markdown avec markdownlint
   markdownlint /tmp/commit_message_${COMMIT_ID}.md

   # 4. Si validation OK, committer avec le fichier
   git add -A
   git commit -F /tmp/commit_message_${COMMIT_ID}.md

   # 5. Nettoyer le fichier temporaire
   rm /tmp/commit_message_${COMMIT_ID}.md
   ```

   **Avantages:**
   - Messages de commit bien formatés et lisibles
   - Validation automatique du Markdown (syntaxe, liens, etc.)
   - Génération automatique de changelogs exploitables
   - Cohérence entre documentation et commits

   **Configuration markdownlint recommandée:**

   Créer `.markdownlint.json` à la racine du projet:

   ```json
   {
     "default": true,
     "MD013": false,
     "MD033": false,
     "MD041": false,
     "line-length": false,
     "no-inline-html": false,
     "first-line-heading": false
   }
   ```

   **Alternative avec éditeur:**

   ```bash
   # Ouvrir l'éditeur pour rédiger le message
   COMMIT_ID=$(shuf -i 1000-9999 -n 1)
   $EDITOR /tmp/commit_message_${COMMIT_ID}.md
   markdownlint /tmp/commit_message_${COMMIT_ID}.md && \
     git add -A && \
     git commit -F /tmp/commit_message_${COMMIT_ID}.md && \
     rm /tmp/commit_message_${COMMIT_ID}.md
   ```

   **Note:** Pour les commits courts (sans description détaillée), `git commit -m` reste acceptable.

### Outils de Qualité

#### Ruff (Linting et Formatting)

Configuration dans `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "C", "B", "UP", "N", "RUF"]
ignore = []

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

Commandes:
```bash
make lint        # Vérification sans modifications
make lint-fix    # Auto-correction
```

#### Pytest (Testing)

```bash
make test                              # Tous les tests avec couverture
pytest tests/test_events.py -v        # Tests spécifiques
pytest -k "user" -v                    # Tests matching pattern
pytest --cov=app --cov-report=term    # Rapport de couverture
```

### Workflow de Développement

1. **Créer une branche depuis main**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feat/nouvelle-fonctionnalite
   ```

2. **Développer avec commits fréquents**
   ```bash
   # Faire des modifications
   git add -A
   git commit -m "feat(api): ajout endpoint de recherche"
   ```

3. **Vérifier la qualité**
   ```bash
   make lint        # Vérifier le code
   make test        # Exécuter les tests
   ```

4. **Pousser et créer une PR**
   ```bash
   git push -u origin feat/nouvelle-fonctionnalite
   # Créer une Pull Request sur GitHub
   ```

5. **Après merge, nettoyer**
   ```bash
   git checkout main
   git pull origin main
   git branch -d feat/nouvelle-fonctionnalite
   ```

### Documentation

- **Code**: Docstrings pour toutes les fonctions publiques
- **API**: OpenAPI automatique via FastAPI
- **Architecture**: CLAUDE.md pour chaque service
- **Événements**: docs/events.md pour le système d'événements
- **Sécurité**: docs/security.md pour l'authentification/autorisation

Cette standardisation assure la cohérence et la maintenabilité à travers tous les microservices AfriCare.
