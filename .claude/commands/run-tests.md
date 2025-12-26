---
name: run-tests
description: Exécute les tests unitaires et d'intégration avec rapport de couverture
---

# Exécuter les Tests AfriCare

Cette commande exécute les tests du service core-africare-identity avec différentes options de filtrage, couverture et génération de rapports.

## Commandes Rapides

### Tests Unitaires (sans services externes)

```bash
make test-unit
# Équivalent: pytest tests/ -v -m "not integration" --cov=app
```

### Tests d'Intégration (PostgreSQL + Redis réels)

```bash
# 1. Démarrer les services de test (ports exotiques 5433, 6380)
make test-services-up

# 2. Exécuter les tests d'intégration
make test-integration
# Équivalent: pytest tests/ -v -m integration --cov=app

# 3. Arrêter les services de test
make test-services-down
```

### Tous les Tests

```bash
make test-all
# Démarre services, exécute tous tests, arrête services
# Génère rapport de couverture HTML dans htmlcov/
```

## Commandes Avancées

### Tests Spécifiques

```bash
# Fichier spécifique
poetry run pytest tests/test_events.py -v

# Test unique
poetry run pytest tests/test_events.py::test_publish_event -v

# Pattern matching
poetry run pytest -k "patient" -v
poetry run pytest -k "patient and not delete" -v
```

### Par Marqueur

```bash
# Intégration uniquement
poetry run pytest -m integration -v

# Unitaires uniquement
poetry run pytest -m "not integration" -v

# Tests async
poetry run pytest -m asyncio -v
```

### Couverture Détaillée

```bash
# Rapport terminal avec lignes manquantes
poetry run pytest --cov=app --cov-report=term-missing

# Rapport HTML interactif
poetry run pytest --cov=app --cov-report=html
# Ouvrir: open htmlcov/index.html

# Rapport XML (pour CI)
poetry run pytest --cov=app --cov-report=xml

# Combiné
poetry run pytest --cov=app --cov-report=term-missing --cov-report=html --cov-report=xml
```

### Options Utiles

```bash
# Verbose avec output détaillé
poetry run pytest -v -s

# Arrêter au premier échec
poetry run pytest -x

# Arrêter après N échecs
poetry run pytest --maxfail=3

# Derniers tests échoués uniquement
poetry run pytest --lf

# Tests modifiés uniquement (depuis dernier commit)
poetry run pytest --co -q | head -20
```

## Infrastructure de Test

### Services Docker de Test

**Fichier**: `docker-compose.test.yaml`

Services isolés sur ports exotiques pour éviter conflits:

| Service | Port Test | Port Dev |
|---------|-----------|----------|
| PostgreSQL | 5433 | 5432 |
| Redis | 6380 | 6379 |

### Commandes Services

```bash
# Démarrer services de test
make test-services-up

# Vérifier statut
make test-services-status

# Voir logs
docker-compose -f docker-compose.test.yaml logs -f

# Arrêter proprement
make test-services-down
```

### Détection Automatique Environnement

Le `conftest.py` détecte automatiquement CI vs local:

```python
# En CI (GitHub Actions): ports standard 5432, 6379
# En local: ports exotiques 5433, 6380

IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"
TEST_PORTS = {
    "postgres": 5432 if IS_GITHUB_ACTIONS else 5433,
    "redis": 6379 if IS_GITHUB_ACTIONS else 6380,
}
```

## Structure des Tests

```
tests/
├── conftest.py                    # Fixtures partagées
├── integration/                   # Tests avec services réels
│   ├── test_database_integration.py   # PostgreSQL
│   └── test_redis_integration.py      # Redis
├── unit/                          # Tests avec mocks
│   ├── test_events.py
│   ├── test_patient_service.py
│   └── test_professional_service.py
└── fixtures/                      # Données de test
    └── sample_data.py
```

## Fixtures Importantes

### Session Base de Données

```python
@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Session avec rollback automatique après chaque test."""
    async with async_session_maker() as session:
        yield session
        await session.rollback()  # Auto-cleanup
```

### Client Redis

```python
@pytest.fixture
async def redis_client(test_redis_client):
    """Client Redis avec flushdb automatique."""
    yield test_redis_client
    await test_redis_client.flushdb()  # Auto-cleanup
```

### Client HTTP FastAPI

```python
@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Client HTTP pour tests API."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
```

## Patterns de Test TDD

### 1. RED - Écrire le Test d'Abord

```python
@pytest.mark.asyncio
async def test_create_patient_with_valid_data(db_session):
    """Test: création patient avec données valides."""
    # Arrange
    patient_data = PatientCreate(
        first_name="Amadou",
        last_name="Diallo",
        email="amadou@example.sn",
        phone="+221771234567",
    )

    # Act
    result = await patient_service.create(db_session, patient_data)

    # Assert
    assert result.id is not None
    assert result.email == "amadou@example.sn"
    assert result.is_active is True
```

### 2. GREEN - Implémenter le Minimum

Écrire juste assez de code pour passer le test.

### 3. REFACTOR - Améliorer Sans Casser

Refactorer en gardant les tests verts.

## Bonnes Pratiques

### Nommage des Tests

```python
# Format: test_{action}_{condition}_{expected_result}

# Bon
async def test_create_patient_with_valid_data_creates_record()
async def test_delete_patient_under_investigation_raises_blocked_error()

# Mauvais
async def test_patient()
async def test_1()
```

### Assertions Spécifiques

```python
# Bon - Assertions claires
assert patient.email == "expected@example.com"
assert patient.is_active is True
assert patient.created_at <= datetime.now(UTC)

# Mauvais - Assertions génériques
assert patient is not None
assert patient  # truthy check
```

### Isolation des Tests

```python
# Chaque test doit être indépendant
# Utiliser fixtures avec auto-cleanup
# Ne pas partager d'état entre tests

@pytest.fixture
async def clean_patient(db_session) -> Patient:
    """Crée un patient propre pour chaque test."""
    patient = Patient(...)
    db_session.add(patient)
    await db_session.commit()
    return patient
```

### Timeout pour Tests Async

```python
@pytest.mark.timeout(30)  # 30 secondes max
@pytest.mark.asyncio
async def test_long_running_operation():
    result = await slow_operation()
    assert result is not None
```

## Checklist Avant Commit

- [ ] `make lint` passe sans erreur
- [ ] `make test-unit` passe (tests rapides)
- [ ] `make test-integration` passe (avec services)
- [ ] Couverture ≥ 80%
- [ ] Nouveaux tests pour nouveau code

## Ressources

- **Configuration pytest**: `pyproject.toml` section `[tool.pytest]`
- **Fixtures**: `tests/conftest.py`
- **Documentation**: `docs/testing.md`
