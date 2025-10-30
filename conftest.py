"""
Configuration pytest pour les tests avec services Docker réels.

Ce fichier configure les fixtures pytest pour utiliser les services
lancés via docker-compose.test.yaml sur des ports exotiques.

Usage:
    docker-compose -f docker-compose.test.yaml up -d
    poetry run pytest
    docker-compose -f docker-compose.test.yaml down -v
"""

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base

# Configuration des ports de test
# Si exécuté dans GitHub Actions, utilise les ports standards des services
# Sinon utilise les ports exotiques pour éviter les conflits en local
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"

TEST_PORTS = {
    "postgres": 5432 if IS_GITHUB_ACTIONS else 5433,
    "redis": 6379 if IS_GITHUB_ACTIONS else 6380,
}

# Variables d'environnement pour les tests
# Respecte les variables déjà définies (ex: dans GitHub Actions)
TEST_ENV = {
    "SQLALCHEMY_DATABASE_URI": os.getenv(
        "SQLALCHEMY_DATABASE_URI",
        f"postgresql+asyncpg://core-africare-identity_test:test_password@localhost:{TEST_PORTS['postgres']}/core-africare-identity_test",
    ),
    "REDIS_URL": os.getenv("REDIS_URL", f"redis://localhost:{TEST_PORTS['redis']}/0"),
    "ENVIRONMENT": os.getenv("ENVIRONMENT", "development"),  # Changed from "test" to "development"
    "DEBUG": os.getenv("DEBUG", "false"),
    # Keycloak (test mode)
    "KEYCLOAK_SERVER_URL": os.getenv("KEYCLOAK_SERVER_URL", "http://localhost:8080"),
    "KEYCLOAK_REALM": os.getenv("KEYCLOAK_REALM", "africare"),
    "KEYCLOAK_CLIENT_ID": os.getenv("KEYCLOAK_CLIENT_ID", "core-africare-identity"),
    # OpenTelemetry (test mode)
    "OTEL_SERVICE_NAME": os.getenv("OTEL_SERVICE_NAME", "core-africare-identity-test"),
    "OTEL_EXPORTER_OTLP_ENDPOINT": os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"
    ),
    "OTEL_EXPORTER_OTLP_PROTOCOL": os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc"),
    "OTEL_EXPORTER_OTLP_INSECURE": os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true"),
}

# Appliquer les variables d'environnement de test (ne remplace pas si déjà définies)
for key, value in TEST_ENV.items():
    if key not in os.environ:
        os.environ[key] = value


# ============================================================================
# Fixtures PostgreSQL
# ============================================================================


@pytest.fixture(scope="session")
def event_loop():
    """Crée un event loop pour toute la session de tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    """
    Crée le moteur SQLAlchemy de test.

    Utilise PostgreSQL sur le port 5433 (docker-compose.test.yaml).
    """
    engine = create_async_engine(
        TEST_ENV["SQLALCHEMY_DATABASE_URI"],
        echo=False,
        pool_pre_ping=True,
    )

    # Créer les tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Nettoyer les tables après tous les tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Fournit une session de base de données pour chaque test.

    La session est rollback après chaque test pour isolation.
    """
    session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        yield session
        await session.rollback()


# ============================================================================
# Fixtures Redis
# ============================================================================


@pytest.fixture(scope="session")
async def test_redis_client():
    """
    Crée le client Redis de test.

    Utilise Redis sur le port 6380 (docker-compose.test.yaml).
    """
    client = Redis.from_url(
        TEST_ENV["REDIS_URL"],
        encoding="utf-8",
        decode_responses=True,
    )

    # Vérifier la connexion
    await client.ping()

    yield client

    # Nettoyer après tous les tests
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def redis_client(test_redis_client):
    """
    Fournit un client Redis pour chaque test.

    Le cache est nettoyé après chaque test pour isolation.
    """
    yield test_redis_client

    # Nettoyer le cache après chaque test
    await test_redis_client.flushdb()


# ============================================================================
# Fixtures communes
# ============================================================================


@pytest.fixture(autouse=True)
async def cleanup_between_tests():
    """
    Fixture automatique qui nettoie entre chaque test.

    Garantit l'isolation des tests.
    """
    yield
    # Le nettoyage est géré par les fixtures db_session et redis_client


@pytest.fixture
def test_env():
    """Fournit les variables d'environnement de test."""
    return TEST_ENV.copy()


@pytest.fixture
def test_ports():
    """Fournit les ports de test."""
    return TEST_PORTS.copy()
