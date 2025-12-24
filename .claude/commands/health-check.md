---
name: health-check
description: Vérifie l'état du service et de ses dépendances (PostgreSQL, Redis, Keycloak, HAPI FHIR)
---

# Vérifier l'État du Service

Cette commande vérifie l'état de santé du service core-africare-identity et de toutes ses dépendances.

## Commandes Rapides

### Vérification Complète

```bash
# Vérifier tous les services
make health-check

# Ou manuellement
curl -s http://localhost:8001/api/v1/health | jq
```

### Services Individuels

```bash
# PostgreSQL
pg_isready -h localhost -p 5432 -U core-africare-identity

# Redis
redis-cli -p 6379 ping

# Keycloak
curl -s http://localhost:8080/health/ready | jq

# HAPI FHIR
curl -s http://localhost:8090/fhir/metadata | jq '.status'
```

## Endpoint Health Check

### URL

```
GET /api/v1/health
```

### Réponse Succès (200 OK)

```json
{
  "status": "healthy",
  "service": "core-africare-identity",
  "version": "0.1.0",
  "timestamp": "2025-01-15T10:30:00+00:00",
  "dependencies": {
    "database": {
      "status": "healthy",
      "latency_ms": 2.5,
      "details": {
        "driver": "postgresql+asyncpg",
        "server_version": "18.0"
      }
    },
    "redis": {
      "status": "healthy",
      "latency_ms": 0.8,
      "details": {
        "server_version": "7.2.3",
        "connected_clients": 5
      }
    },
    "keycloak": {
      "status": "healthy",
      "latency_ms": 15.2,
      "details": {
        "realm": "africare-dev",
        "version": "26.4"
      }
    },
    "hapi_fhir": {
      "status": "healthy",
      "latency_ms": 25.0,
      "details": {
        "fhir_version": "R4",
        "server_version": "7.6.0"
      }
    }
  }
}
```

### Réponse Dégradée (200 OK avec warnings)

```json
{
  "status": "degraded",
  "service": "core-africare-identity",
  "version": "0.1.0",
  "timestamp": "2025-01-15T10:30:00+00:00",
  "dependencies": {
    "database": {
      "status": "healthy",
      "latency_ms": 2.5
    },
    "redis": {
      "status": "unhealthy",
      "error": "Connection refused",
      "details": {
        "retry_in_seconds": 30
      }
    }
  }
}
```

### Réponse Échec (503 Service Unavailable)

```json
{
  "status": "unhealthy",
  "service": "core-africare-identity",
  "timestamp": "2025-01-15T10:30:00+00:00",
  "dependencies": {
    "database": {
      "status": "unhealthy",
      "error": "Connection timeout after 5000ms"
    }
  }
}
```

## Implémentation

### Endpoint Health Check

**Fichier**: `app/api/v1/health.py`

```python
"""Health check endpoint."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import check_database_health
from app.core.redis import check_redis_health
from app.infrastructure.keycloak import check_keycloak_health
from app.infrastructure.fhir import check_fhir_health

router = APIRouter()


class DependencyHealth(BaseModel):
    status: str
    latency_ms: float | None = None
    error: str | None = None
    details: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str
    dependencies: dict[str, DependencyHealth]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Vérifie l'état de santé du service et de ses dépendances.

    Returns:
        HealthResponse avec statut global et détails par dépendance
    """
    dependencies = {}
    all_healthy = True

    # Vérifier PostgreSQL
    db_health = await check_database_health()
    dependencies["database"] = db_health
    if db_health.status != "healthy":
        all_healthy = False

    # Vérifier Redis
    redis_health = await check_redis_health()
    dependencies["redis"] = redis_health
    if redis_health.status != "healthy":
        all_healthy = False

    # Vérifier Keycloak (optionnel en dev)
    if settings.KEYCLOAK_SERVER_URL:
        kc_health = await check_keycloak_health()
        dependencies["keycloak"] = kc_health
        # Keycloak non-critique pour status global

    # Vérifier HAPI FHIR
    if settings.HAPI_FHIR_BASE_URL:
        fhir_health = await check_fhir_health()
        dependencies["hapi_fhir"] = fhir_health
        # FHIR non-critique pour status global

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        service=settings.OTEL_SERVICE_NAME,
        version=settings.VERSION,
        timestamp=datetime.now(UTC).isoformat(),
        dependencies=dependencies,
    )
```

### Vérification Base de Données

**Fichier**: `app/core/database.py`

```python
import time
from sqlalchemy import text

async def check_database_health() -> DependencyHealth:
    """Vérifie la connexion à PostgreSQL."""
    try:
        start = time.perf_counter()
        async with async_session_maker() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar()

        latency = (time.perf_counter() - start) * 1000

        return DependencyHealth(
            status="healthy",
            latency_ms=round(latency, 2),
            details={
                "driver": "postgresql+asyncpg",
                "server_version": version.split()[1] if version else "unknown",
            },
        )
    except Exception as e:
        return DependencyHealth(
            status="unhealthy",
            error=str(e),
        )
```

### Vérification Redis

**Fichier**: `app/core/redis.py`

```python
import time

async def check_redis_health() -> DependencyHealth:
    """Vérifie la connexion à Redis."""
    try:
        start = time.perf_counter()
        info = await redis_client.info("server")
        latency = (time.perf_counter() - start) * 1000

        return DependencyHealth(
            status="healthy",
            latency_ms=round(latency, 2),
            details={
                "server_version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
            },
        )
    except Exception as e:
        return DependencyHealth(
            status="unhealthy",
            error=str(e),
        )
```

## Scripts de Diagnostic

### Script Complet

```bash
#!/bin/bash
# scripts/health-check.sh

echo "=== Health Check: core-africare-identity ==="

# Service principal
echo -n "API Health: "
curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/v1/health
echo ""

# PostgreSQL
echo -n "PostgreSQL: "
pg_isready -h localhost -p 5432 -U core-africare-identity -q && echo "OK" || echo "FAILED"

# Redis
echo -n "Redis: "
redis-cli -p 6379 ping | grep -q PONG && echo "OK" || echo "FAILED"

# Keycloak
echo -n "Keycloak: "
curl -s http://localhost:8080/health/ready | grep -q UP && echo "OK" || echo "FAILED"

# HAPI FHIR
echo -n "HAPI FHIR: "
curl -s http://localhost:8090/fhir/metadata | grep -q "active" && echo "OK" || echo "FAILED"

echo "=== Done ==="
```

### Docker Compose Health

```yaml
# docker-compose.yaml
services:
  core-africare-identity:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  postgres:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U core-africare-identity"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

## Monitoring Kubernetes

### Liveness Probe

```yaml
livenessProbe:
  httpGet:
    path: /api/v1/health
    port: 8001
  initialDelaySeconds: 15
  periodSeconds: 20
  failureThreshold: 3
```

### Readiness Probe

```yaml
readinessProbe:
  httpGet:
    path: /api/v1/health
    port: 8001
  initialDelaySeconds: 5
  periodSeconds: 10
```

## Checklist Diagnostic

- [ ] API répond sur `/api/v1/health`
- [ ] PostgreSQL accessible (port 5432)
- [ ] Redis accessible (port 6379)
- [ ] Keycloak accessible (port 8080) - optionnel en dev
- [ ] HAPI FHIR accessible (port 8090) - optionnel en dev
- [ ] Latences < 100ms pour DB et Redis
- [ ] Pas d'erreurs dans les logs: `docker-compose logs -f`

## Ressources

- **Configuration**: Voir `app/core/config.py`
- **Docker Compose**: `docker-compose.yaml`
- **Logs**: `docker-compose logs core-africare-identity`
