# core-africare-identity

**Service de gestion d'identité et d'authentification pour la plateforme AfriCare**

## 📋 Présentation

Le service **core-africare-identity** est un microservice fondamental de la plateforme AfriCare responsable de la gestion des identités des patients et des professionnels de santé. Il s'intègre avec Keycloak pour l'authentification et gère les données démographiques et professionnelles dans le contexte africain.

### Périmètre fonctionnel

**Ce service gère :**
- ✅ Identité des patients (données démographiques, contact, localisation GPS)
- ✅ Identité des professionnels de santé (informations professionnelles, établissements)
- ✅ Intégration Keycloak (authentification JWT, RBAC)
- ✅ Vérification d'identité (KYC)
- ✅ Identifiants nationaux (CNI, passeport, numéro d'ordre professionnel)
- ✅ Support du contexte africain (GPS pour zones rurales, langues fr/en)
- ✅ Déduplication des identités
- ✅ Historique des modifications d'identité

**Ce service NE gère PAS :**
- ❌ Données médicales (groupe sanguin, allergies, historique) → `core-africare-ehr`
- ❌ Rendez-vous médicaux → `apps-africare-appointment-scheduling`
- ❌ Prescriptions → `core-africare-prescription`
- ❌ Facturation → `core-africare-billing`

## 🏗️ Architecture

### Stack technique

- **Framework**: FastAPI (async)
- **Base de données**: PostgreSQL 18 (SQLAlchemy 2.0 avec Mapped[])
- **Authentification**: Keycloak (python-keycloak)
- **Messaging**: Azure Event Hub (SDK natif)
- **Observabilité**: OpenTelemetry (traces, métriques, logs)
- **Validation**: Pydantic v2
- **Migrations**: Alembic
- **Tests**: pytest + pytest-asyncio
- **Linting**: Ruff
- **Conteneurs**: Docker + Docker Compose

### Modèles de données

#### Patient
- Données démographiques (nom, prénom, date de naissance, genre)
- Contact (email, téléphones, contact d'urgence)
- Adresse (avec support GPS pour zones rurales)
- Identifiants nationaux (CNI, passeport)
- Langue préférée (fr, en)
- Vérification d'identité

#### Professional
- Informations personnelles (nom, prénom, titre)
- Informations professionnelles (spécialité, type, numéro d'ordre CNOM)
- Contact professionnel
- Établissement de santé (nom, type, adresse, localisation)
- Qualifications et expérience
- Disponibilité pour consultations
- Signature numérique (pour prescriptions électroniques)

### Endpoints API

#### Patients (`/api/v1/patients`)
- `POST /` - Créer un patient (admin/professional)
- `GET /{patient_id}` - Récupérer par ID
- `GET /keycloak/{keycloak_user_id}` - Récupérer par Keycloak ID (self-service)
- `PUT /{patient_id}` - Mettre à jour (owner/admin/professional)
- `DELETE /{patient_id}` - Soft delete (admin uniquement)
- `GET /` - Rechercher avec filtres (admin/professional)
- `POST /{patient_id}/verify` - Vérifier identité (professional/admin)

#### Professionnels (`/api/v1/professionals`)
- `POST /` - Créer un professionnel (admin)
- `GET /{professional_id}` - Récupérer par ID
- `GET /keycloak/{keycloak_user_id}` - Récupérer par Keycloak ID (self-service)
- `GET /professional-id/{professional_id}` - Rechercher par numéro d'ordre
- `PUT /{professional_id}` - Mettre à jour (owner/admin)
- `DELETE /{professional_id}` - Soft delete (admin uniquement)
- `GET /` - Rechercher avec filtres (authenticated)
- `POST /{professional_id}/verify` - Vérifier (admin uniquement)
- `POST /{professional_id}/availability` - Changer disponibilité (owner/admin)

## 🚀 Installation et Démarrage

### Prérequis

- Python ≥3.12,<3.14
- Poetry ≥1.8
- Docker & Docker Compose
- PostgreSQL 18 (via Docker)

### Installation locale

```bash
# 1. Cloner le repository
git clone https://github.com/btall/core-africare-identity.git
cd core-africare-identity

# 2. Installer les dépendances avec Poetry
make install

# 3. Configurer les variables d'environnement
cp .env.development .env
# Modifier .env si nécessaire

# 4. Démarrer les services Docker (PostgreSQL)
docker-compose up -d

# 5. Créer les migrations de base de données
make migrate MESSAGE="Initial migration"
make migrate-up

# 6. Lancer le serveur de développement
make run
```

Le service sera accessible sur http://localhost:8001

### Documentation API

- **Swagger UI**: http://localhost:8001/docs
- **ReDoc**: http://localhost:8001/redoc
- **OpenAPI JSON**: http://localhost:8001/openapi.json

## 🔐 Sécurité et Authentification

Le service utilise **Keycloak** pour l'authentification JWT et le contrôle d'accès basé sur les rôles (RBAC).

### Rôles disponibles

- **admin** - Administrateur système (tous les droits)
- **professional** - Professionnel de santé (accès patients, vérification)
- **patient** - Patient (accès self-service à son profil)

### Exemple d'utilisation

```python
from fastapi import APIRouter, Depends
from app.core.security import require_roles, get_current_user

router = APIRouter()

# Endpoint nécessitant le rôle "patient" OU "professional" (OR logic)
@router.get("/data", dependencies=[Depends(require_roles("patient", "professional"))])
async def get_data():
    return {"data": "sensitive information"}

# Endpoint nécessitant les rôles "admin" ET "manager" (AND logic)
@router.delete("/critical", dependencies=[Depends(require_roles("admin", "manager", require_all=True))])
async def delete_critical_data():
    return {"status": "deleted"}

# Récupérer l'utilisateur actuel
@router.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    return {
        "user_id": current_user["sub"],
        "email": current_user.get("email"),
        "roles": current_user.get("realm_access", {}).get("roles", [])
    }
```

Pour plus de détails, consultez [docs/security.md](docs/security.md).

## 📡 Système d'événements

Le service publie des événements via **Azure Event Hub** pour la communication inter-services.

### Événements publiés

**Patients:**
- `identity.patient.created` - Patient créé
- `identity.patient.updated` - Patient mis à jour
- `identity.patient.deactivated` - Patient désactivé
- `identity.patient.verified` - Identité patient vérifiée

**Professionnels:**
- `identity.professional.created` - Professionnel créé
- `identity.professional.updated` - Professionnel mis à jour
- `identity.professional.deactivated` - Professionnel désactivé
- `identity.professional.verified` - Professionnel vérifié
- `identity.professional.availability_changed` - Disponibilité modifiée

### Exemple de publication

```python
from app.core.events import publish
from datetime import datetime, UTC

await publish("identity.patient.created", {
    "patient_id": patient.id,
    "keycloak_user_id": patient.keycloak_user_id,
    "first_name": patient.first_name,
    "last_name": patient.last_name,
    "created_by": current_user["sub"],
    "timestamp": datetime.now(UTC).isoformat()
})
```

Pour plus de détails, consultez [docs/events.md](docs/events.md).

## 🧪 Tests

```bash
# Lancer tous les tests avec couverture
make test

# Lancer des tests spécifiques
poetry run pytest tests/test_patient_service.py -v

# Lancer les tests avec pattern
poetry run pytest -k "patient" -v

# Rapport de couverture détaillé
poetry run pytest --cov=app --cov-report=html
```

## 🛠️ Développement

### Commandes Make disponibles

```bash
make install       # Installer les dépendances
make run           # Lancer le serveur (port 8001)
make run PORT=8080 # Lancer sur un port spécifique
make lint          # Vérifier la qualité du code (ruff)
make lint-fix      # Corriger automatiquement le code
make test          # Lancer les tests avec couverture
make migrate       # Créer une migration Alembic
make migrate-up    # Appliquer les migrations
make migrate-down  # Annuler la dernière migration
make clean         # Nettoyer les fichiers générés
make help          # Afficher l'aide
```

### Structure du projet

```
core-africare-identity/
├── app/
│   ├── main.py              # Point d'entrée FastAPI
│   ├── api/
│   │   └── v1/
│   │       ├── api.py       # Router principal
│   │       ├── health.py    # Health check
│   │       └── endpoints/
│   │           ├── patients.py        # Endpoints patients
│   │           └── professionals.py   # Endpoints professionnels
│   ├── core/
│   │   ├── config.py        # Configuration Pydantic
│   │   ├── database.py      # SQLAlchemy async setup
│   │   ├── events.py        # Azure Event Hub SDK
│   │   └── security.py      # Keycloak JWT + RBAC
│   ├── models/
│   │   ├── patient.py       # Modèle SQLAlchemy Patient
│   │   └── professional.py  # Modèle SQLAlchemy Professional
│   ├── schemas/
│   │   ├── utils.py         # Annotations réutilisables
│   │   ├── patient.py       # Schémas Pydantic Patient
│   │   └── professional.py  # Schémas Pydantic Professional
│   └── services/
│       ├── patient_service.py       # Logique métier Patient
│       └── professional_service.py  # Logique métier Professional
├── alembic/                 # Migrations de base de données
├── docs/                    # Documentation
│   ├── database.md          # Configuration PostgreSQL
│   ├── events.md            # Système d'événements
│   └── security.md          # Authentification et autorisation
├── tests/                   # Tests unitaires et d'intégration
├── .env.development         # Variables dev (localhost)
├── .env.example             # Template de configuration
├── docker-compose.yaml      # Stack local (PostgreSQL)
├── Makefile                 # Commandes de développement
├── pyproject.toml           # Dépendances Poetry
└── alembic.ini              # Configuration Alembic
```

## 📊 Observabilité

Le service est instrumenté avec **OpenTelemetry** pour une observabilité complète :

- **Traces distribuées** : Toutes les requêtes HTTP, opérations DB, événements
- **Métriques** : Compteurs, histogrammes personnalisés
- **Logs structurés** : Corrélation avec traces (trace_id, span_id)
- **Attributs contextuels** : user_id, resource_type, action

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def create_patient(db, patient_data, current_user_id):
    with tracer.start_as_current_span("create_patient") as span:
        span.set_attribute("patient.keycloak_user_id", patient_data.keycloak_user_id)

        patient = Patient(**patient_data.model_dump())
        db.add(patient)
        await db.commit()

        span.set_attribute("patient.id", patient.id)
        span.add_event("Patient créé avec succès")

        return patient
```

## 🌍 Support du contexte africain

Le service prend en compte les spécificités du contexte africain :

- **GPS pour zones rurales** : Latitude/longitude pour localisation précise
- **Identifiants nationaux** : CNI, passeport, numéro d'ordre professionnel
- **Langues supportées** : Français (fr) et Anglais (en)
- **Contact d'urgence** : Informations complètes pour situations critiques
- **Régions administratives** : Support des divisions territoriales locales

## 📚 Documentation

- **[Sécurité et Autorisation](docs/security.md)** - Authentification Keycloak et RBAC
- **[Système d'Événements](docs/events.md)** - Azure Event Hub et patterns événementiels
- **[Base de Données](docs/database.md)** - PostgreSQL 18 et migrations Alembic
- **[CLAUDE.md](CLAUDE.md)** - Guide complet pour développement avec Claude Code

## 🤝 Contribution

1. Fork le projet
2. Créer une branche feature (`git checkout -b feat/nouvelle-fonctionnalite`)
3. Commiter les changements (`git commit -m 'feat(identity): ajout fonctionnalité'`)
4. Pousser vers la branche (`git push origin feat/nouvelle-fonctionnalite`)
5. Ouvrir une Pull Request

**Conventions de commits** : [Conventional Commits v1.0.0](https://www.conventionalcommits.org/)

## 📄 Licence

Copyright © 2025 AfriCare Team

## 👥 Auteurs

AfriCare Team - [team@africare.app](mailto:team@africare.app)

---

**Version**: 0.1.0
**Port par défaut**: 8001
**Documentation API**: http://localhost:8001/docs
