<!-- markdownlint-disable MD055 MD056 MD032 -->
# Guide des Tests

Ce document explique comment utiliser l'infrastructure de tests de core-africare-identity.

## Vue d'ensemble

Le projet utilise une stratégie de tests à deux niveaux :

1. **Tests unitaires** : Rapides, avec mocks, pour tester la logique isolément
2. **Tests d'intégration** : Avec vrais services Docker, pour tester l'intégration complète

## Architecture des tests

```
tests/
├── __init__.py
├── test_*.py                           # Tests unitaires (mocks)
└── integration/
    ├── __init__.py
    ├── test_database_integration.py    # Tests PostgreSQL
    └── test_redis_integration.py       # Tests Redis
```

## Configuration des tests

### Fichiers de configuration

- **`conftest.py`** : Fixtures pytest pour services Docker
- **`docker-compose.test.yaml`** : Services de test sur ports exotiques
- **`pytest.ini`** : Configuration pytest et markers

### Ports des services de test

Pour éviter les conflits avec les services de développement, les tests utilisent des ports exotiques :

| Service | Port développement | Port test |
|---------|-------------------|-----------|
| PostgreSQL | 5432 | **5433** |
| Redis | 6379 | **6380** |

## Utilisation

### 1. Tests unitaires (rapides)

Tests avec mocks, ne nécessitent pas Docker :

```bash
# Lancer les tests unitaires
make test
# ou
make test-unit

# Avec verbose
poetry run pytest tests/ -v -m "not integration"
```

### 2. Tests d'intégration (complets)

Tests avec vrais services Docker :

```bash
# Démarrer les services de test
make test-services-up

# Lancer les tests d'intégration
make test-integration

# Arrêter les services
make test-services-down
```

### 3. Tous les tests

Lancer tous les tests (unitaires + intégration) en une commande :

```bash
# Lance automatiquement les services Docker, exécute tous les tests, génère le rapport HTML
make test-all

# Voir le rapport de couverture
open htmlcov/index.html
```

### 4. Gestion des services de test

```bash
# Démarrer les services
make test-services-up

# Vérifier le statut
make test-services-status

# Arrêter les services
make test-services-down

# Nettoyer complètement (avec volumes)
make test-services-clean
```

## Écriture de tests

### Tests unitaires

Utilisez des mocks pour isoler la logique :

```python
# tests/test_my_feature.py
from unittest.mock import AsyncMock, patch

import pytest


async def test_my_feature():
    """Test unitaire avec mocks."""
    with patch("app.core.events.publish") as mock_publish:
        mock_publish.return_value = AsyncMock()

        # Votre test ici
        result = await my_function()

        assert result == expected_value
        mock_publish.assert_called_once()
```

### Tests d'intégration

Utilisez les fixtures pour les vrais services :

```python
# tests/integration/test_my_integration.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_operation(db_session: AsyncSession):
    """Test d'intégration avec PostgreSQL réel."""
    # Créer une entité
    patient = Patient(
        keycloak_user_id="test-user-123",
        first_name="Amadou",
        last_name="Diallo",
        date_of_birth="1990-05-15",
        gender="male"
    )
    db_session.add(patient)
    await db_session.commit()
    await db_session.refresh(patient)

    # Vérifications
    assert patient.id is not None
    assert patient.created_at is not None
```

## Markers pytest

Le projet utilise des markers pour catégoriser les tests :

```python
@pytest.mark.integration  # Test d'intégration (nécessite Docker)
@pytest.mark.asyncio      # Test asynchrone
@pytest.mark.slow         # Test lent (>5 secondes)
```

Lancer des tests par marker :

```bash
# Tests d'intégration uniquement
poetry run pytest -m integration

# Exclure les tests lents
poetry run pytest -m "not slow"

# Tests async uniquement
poetry run pytest -m asyncio
```

## Fixtures disponibles

### Database

- **`db_session`** : Session PostgreSQL async, auto-rollback après chaque test
- **`test_engine`** : Moteur SQLAlchemy de test (scope: session)

### Redis

- **`redis_client`** : Client Redis async, auto-flush après chaque test
- **`test_redis_client`** : Client Redis de test (scope: session)

### Configuration

- **`test_env`** : Variables d'environnement de test
- **`test_ports`** : Ports des services de test

## Couverture de code

### Générer le rapport

```bash
# Rapport terminal
make test-all

# Rapport HTML
poetry run pytest --cov=app --cov-report=html
open htmlcov/index.html
```

### Objectif de couverture

- **Minimum requis** : 80%
- **Cible recommandée** : 90%+

## CI/CD

Les tests sont automatiquement exécutés dans GitHub Actions :

- **Tests unitaires** : À chaque push/PR
- **Tests d'intégration** : Avant merge sur `main`

Configuration : `.github/workflows/ci.yaml`

## Troubleshooting

### Les services ne démarrent pas

```bash
# Vérifier les logs
docker-compose -f docker-compose.test.yaml logs

# Nettoyer complètement et recommencer
make test-services-clean
make test-services-up
```

### Conflit de ports

Si les ports exotiques sont déjà utilisés, modifiez `docker-compose.test.yaml` :

```yaml
ports:
  - "5434:5432"  # Changer 5433 -> 5434
```

Puis mettez à jour `conftest.py` :

```python
TEST_PORTS = {
    "postgres": 5434,  # Mettre à jour le port
}
```

### Tests échouent de manière aléatoire

Problème d'isolation entre tests. Vérifiez que :

1. Les fixtures font le nettoyage correctement
2. Les tests n'ont pas d'effets de bord
3. Les services sont bien initialisés (ajoutez des `sleep` si nécessaire)

### Performance lente

```bash
# Lancer uniquement les tests modifiés
poetry run pytest --lf  # last-failed

# Lancer en parallèle (nécessite pytest-xdist)
poetry run pytest -n auto
```

## Bonnes pratiques

1. ✅ **Tests unitaires en premier** : Rapides, exécutés fréquemment
2. ✅ **Tests d'intégration pour les chemins critiques** : Flux utilisateur complets
3. ✅ **Isolation des tests** : Chaque test doit être indépendant
4. ✅ **Nommage clair** : `test_<action>_<expected_result>`
5. ✅ **AAA Pattern** : Arrange, Act, Assert
6. ✅ **Fixtures réutilisables** : Centraliser dans `conftest.py`
7. ⛔ **Éviter les tests flaky** : Pas de `time.sleep()`, utiliser des attentes
8. ⛔ **Éviter les tests trop lents** : Marker avec `@pytest.mark.slow`

## Ressources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest AsyncIO](https://pytest-asyncio.readthedocs.io/)
- [SQLAlchemy Testing](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#joining-a-session-into-an-external-transaction-such-as-for-test-suites)
- [Docker Compose](https://docs.docker.com/compose/)
