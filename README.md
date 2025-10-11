# core-africare-identity

Identity management and Keycloak integration

## Prérequis

- Python >=3.12,<3.14
- Poetry
- PostgreSQL

## Installation

1. Cloner le repository :
```bash
git clone <repository-url>
cd core-africare-identity
```

2. Installer les dépendances avec Poetry :
```bash
poetry install
```

3. Configurer les variables d'environnement :
```bash
cp .env.example .env
# Modifier les variables dans .env selon votre environnement
```

4. Initialiser la base de données :
```bash
poetry run alembic upgrade head
```

## Développement

1. Activer l'environnement virtuel :
```bash
poetry shell
```

2. Lancer le serveur de développement :
```bash
uvicorn app.main:app --reload
```

3. Accéder à la documentation de l'API :
- Swagger UI : http://localhost:8001/docs
- ReDoc : http://localhost:8001/redoc

## Tests

Exécuter les tests :
```bash
poetry run pytest
```

## Sécurité et Authentification

Ce service utilise **Keycloak** pour l'authentification et l'autorisation basée sur les rôles.

Pour des informations détaillées sur l'authentification, l'autorisation, et l'utilisation du décorateur `require_roles()`, consultez la [documentation de sécurité](docs/security.md).

**Exemple d'utilisation rapide:**
```python
from fastapi import APIRouter, Depends
from app.core.security import require_roles

router = APIRouter()

# Endpoint nécessitant le rôle "patient" OU "professional"
@router.get("/data", dependencies=[Depends(require_roles("patient", "professional"))])
async def get_data():
    return {"data": "sensitive information"}

# Endpoint nécessitant les rôles "admin" ET "manager"
@router.delete("/critical", dependencies=[Depends(require_roles("admin", "manager", require_all=True))])
async def delete_critical_data():
    return {"status": "deleted"}
```

## Documentation

- **[Sécurité et Autorisation](docs/security.md)** - Authentification Keycloak et contrôle d'accès basé sur les rôles
- **[Système d'Événements](docs/events.md)** - Intégration Azure Event Hub et patterns événementiels
- **[Base de Données](docs/database.md)** - Configuration et opérations de base de données

## Structure du projet

```
core-africare-identity/
├── app/
│   ├── api/         # Points d'entrée de l'API
│   ├── core/        # Configuration et utilitaires
│   ├── models/      # Modèles de données
│   ├── schemas/     # Schémas Pydantic
│   └── services/    # Services de l'application
├── docs/            # Documentation du service
├── tests/           # Tests
├── alembic/         # Migrations de base de données
├── .env             # Variables d'environnement
└── pyproject.toml   # Dépendances et configuration
```

## Auteur

Africare Team <team@africare.app>
