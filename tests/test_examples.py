"""
Tests pour les endpoints d'exemples de core-africare-identity.

Tests avec SQLAlchemy 2.0 et PostgreSQL.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app


# Configuration de test pour PostgreSQL
@pytest.fixture
def test_session():
    engine = create_engine(
        "sqlite:///./test.db",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    async def get_test_session():
        async with AsyncSession(engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    yield
    app.dependency_overrides.clear()


def test_create_example(test_session):
    """Test de création d'exemple (PostgreSQL)."""
    client = TestClient(app)
    response = client.post(
        f"/{app.title}/examples/", json={"name": "Test Example", "description": "Test description"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Example"
    assert data["description"] == "Test description"
    assert "id" in data
    assert "created_at" in data


def test_get_example(test_session):
    """Test de récupération d'exemple (PostgreSQL)."""
    client = TestClient(app)

    # Créer d'abord un exemple
    create_response = client.post(
        f"/{app.title}/examples/", json={"name": "Get Test", "description": "Get description"}
    )
    created_example = create_response.json()

    # Récupérer l'exemple
    response = client.get(f"/{app.title}/examples/{created_example['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Get Test"
    assert data["id"] == created_example["id"]


def test_list_examples(test_session):
    """Test de listage d'exemples (PostgreSQL)."""
    client = TestClient(app)

    # Créer quelques exemples
    client.post(f"/{app.title}/examples/", json={"name": "Example 1"})
    client.post(f"/{app.title}/examples/", json={"name": "Example 2"})

    # Lister les exemples
    response = client.get(f"/{app.title}/examples/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2


def test_update_example(test_session):
    """Test de mise à jour d'exemple (PostgreSQL)."""
    client = TestClient(app)

    # Créer un exemple
    create_response = client.post(
        f"/{app.title}/examples/", json={"name": "Original", "description": "Original description"}
    )
    created_example = create_response.json()

    # Mettre à jour l'exemple
    response = client.put(
        f"/{app.title}/examples/{created_example['id']}",
        json={"name": "Updated", "description": "Updated description"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated"
    assert data["description"] == "Updated description"


def test_delete_example(test_session):
    """Test de suppression d'exemple (PostgreSQL)."""
    client = TestClient(app)

    # Créer un exemple
    create_response = client.post(f"/{app.title}/examples/", json={"name": "To Delete"})
    created_example = create_response.json()

    # Supprimer l'exemple
    response = client.delete(f"/{app.title}/examples/{created_example['id']}")
    assert response.status_code == 200

    # Vérifier qu'il n'existe plus
    get_response = client.get(f"/{app.title}/examples/{created_example['id']}")
    assert get_response.status_code == 404


def test_health_check():
    """Test du health check (commun aux deux bases)."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
