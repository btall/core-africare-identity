# GitHub Actions - Configuration et Workflows

Ce dossier contient la configuration GitHub Actions pour l'intégration continue (CI) et le déploiement continu (CD) du service core-africare-identity.

## Structure

```
.github/
├── README.md                 # Ce fichier
├── scripts/
│   └── setup-secrets.sh      # Script d'automatisation des secrets GitHub
└── workflows/
    ├── ci.yaml              # Workflow CI (tests, linting, sécurité)
    └── cd.yaml              # Workflow CD (build, push, déploiement)
```

## Configuration Initiale

### 1. Créer les Environnements GitHub

Les environnements doivent être créés manuellement via l'interface GitHub:

1. Aller sur: `https://github.com/btall/core-africare-identity/settings/environments`
2. Créer les 3 environnements suivants:
   - `development`
   - `staging`
   - `production`

**Protection des environnements (recommandé):**

Pour **production**:
- Cocher "Required reviewers" - ajouter au moins 1 reviewer
- Cocher "Wait timer" - définir 5 minutes de délai
- Cocher "Deployment branches" - limiter à `main` uniquement

Pour **staging**:
- Cocher "Deployment branches" - limiter à `develop` et `main`

### 2. Configurer les Secrets et Variables

#### Option A: Utiliser le Script Automatisé (Recommandé)

Le script `setup-secrets.sh` configure automatiquement tous les secrets et variables via GitHub CLI:

```bash
# 1. Installer GitHub CLI si nécessaire
# macOS
brew install gh

# Linux
sudo apt install gh

# 2. S'authentifier
gh auth login

# 3. Configurer les secrets pour chaque environnement
cd .github/scripts

# Development
./setup-secrets.sh development

# Staging
./setup-secrets.sh staging

# Production
./setup-secrets.sh production
```

**Note:** Le script charge les valeurs depuis les fichiers `.env.[environment]` à la racine du projet.

#### Option B: Configuration Manuelle via GitHub CLI

```bash
# Secrets d'environnement
gh secret set KEYCLOAK_CLIENT_SECRET --env production --body "your-secret-value"
gh secret set SQLALCHEMY_DATABASE_URI --env production --body "postgresql+asyncpg://..."

# Variables d'environnement
gh variable set AZURE_EVENTHUB_NAMESPACE --env production --body "africare.servicebus.windows.net"
gh variable set OTEL_SERVICE_NAME --env production --body "core-africare-identity"
```

#### Option C: Configuration Manuelle via Interface Web

1. Aller sur: `https://github.com/btall/core-africare-identity/settings/secrets/actions`
2. Ajouter les secrets requis (voir liste ci-dessous)
3. Aller sur: `https://github.com/btall/core-africare-identity/settings/variables/actions`
4. Ajouter les variables requises

### 3. Liste Complète des Secrets et Variables

#### Secrets (valeurs sensibles - à configurer par environnement)

| Secret | Description | Exemple |
|--------|-------------|---------|
| `KEYCLOAK_SERVER_URL` | URL du serveur Keycloak | `https://auth.africare.sn` |
| `KEYCLOAK_REALM` | Realm Keycloak | `africare` |
| `KEYCLOAK_CLIENT_ID` | Client ID du service | `core-africare-identity` |
| `KEYCLOAK_CLIENT_SECRET` | Client secret Keycloak | `[secret]` |
| `SQLALCHEMY_DATABASE_URI` | URL PostgreSQL complète | `postgresql+asyncpg://user:pass@host/db` |
| `AZURE_EVENTHUB_CONNECTION_STRING` | Connection string Event Hub (fallback) | `Endpoint=sb://...` |
| `AZURE_EVENTHUB_BLOB_STORAGE_CONNECTION_STRING` | Connection string Blob Storage (fallback) | `DefaultEndpointsProtocol=https...` |
| `AZURE_CREDENTIALS` | Credentials Azure pour déploiement | JSON avec service principal |

#### Variables (valeurs publiques - à configurer par environnement)

| Variable | Description | Exemple |
|----------|-------------|---------|
| `PROJECT_NAME` | Nom du projet | `core-africare-identity` |
| `PROJECT_SLUG` | Slug du projet | `identity` |
| `ENVIRONMENT` | Environnement cible | `production` |
| `AZURE_EVENTHUB_NAMESPACE` | FQDN Event Hub namespace | `africare.servicebus.windows.net` |
| `AZURE_EVENTHUB_NAME` | Nom de l'Event Hub | `core-africare-identity` |
| `AZURE_EVENTHUB_CONSUMER_GROUP` | Consumer group | `$Default` |
| `AZURE_EVENTHUB_CONSUMER_SOURCES` | Event Hubs à consommer | `core-africare-identity,core-africare-ehr` |
| `AZURE_BLOB_STORAGE_ACCOUNT_URL` | URL compte Blob Storage | `https://stafricare.blob.core.windows.net` |
| `AZURE_EVENTHUB_BLOB_STORAGE_CONTAINER_NAME` | Container checkpoints | `eventhub-checkpoints` |
| `OTEL_SERVICE_NAME` | Nom du service OpenTelemetry | `core-africare-identity` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Endpoint OpenTelemetry Collector | `https://otel.africare.sn` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Protocole OTLP | `grpc` |
| `OTEL_EXPORTER_OTLP_INSECURE` | Mode insecure OTLP | `false` |
| `ALLOWED_ORIGINS` | Origines CORS autorisées | `https://app.africare.sn,https://admin.africare.sn` |
| `TRUSTED_HOSTS` | Hosts de confiance | `app.africare.sn,*.africare.sn` |
| `SUPPORTED_LOCALES` | Langues supportées | `fr,en` |
| `DEFAULT_LOCALE` | Langue par défaut | `fr` |

### 4. Configurer Azure Credentials pour le Déploiement

Pour permettre le déploiement sur Azure Container Apps, créer un Service Principal:

```bash
# 1. Créer le service principal
az ad sp create-for-rbac \
  --name "sp-core-africare-identity-github" \
  --role contributor \
  --scopes /subscriptions/{subscription-id}/resourceGroups/rg-africare-production \
  --sdk-auth

# 2. Copier la sortie JSON complète

# 3. Ajouter comme secret GitHub
gh secret set AZURE_CREDENTIALS --env production --body '{
  "clientId": "...",
  "clientSecret": "...",
  "subscriptionId": "...",
  "tenantId": "..."
}'
```

## Workflows

### CI Workflow (ci.yaml)

**Déclenchement:**
- Push sur `main`, `develop`, branches `feature/*`, `fix/*`
- Pull requests vers `main`, `develop`
- Déclenchement manuel

**Jobs:**
1. **Lint** - Vérification du code avec Ruff
2. **Test** - Tests unitaires avec coverage (PostgreSQL/MongoDB en service)
3. **Docker Build** - Validation de la construction Docker
4. **Security** - Scan des vulnérabilités avec Safety
5. **CI Success** - Résumé global

**Variables d'environnement pour les tests:**
- Toutes les variables sont définies dans le workflow
- Base de données de test démarrée en service GitHub Actions
- Mocks pour Azure Event Hub et Keycloak

### CD Workflow (cd.yaml)

**Déclenchement:**
- Push sur `main` → déploiement en **production**
- Push sur `develop` → déploiement en **staging**
- Déclenchement manuel avec choix de l'environnement

**Jobs:**
1. **Determine Environment** - Détermine l'environnement cible
2. **Build and Push** - Construction et push de l'image Docker vers GHCR
3. **Deploy** - Déploiement sur Azure Container Apps
4. **Notify** - Notification de déploiement (optionnel)

**Tagging des images:**
- `{environment}-latest` - Dernière image de l'environnement
- `{environment}-{sha}` - Image spécifique par commit
- `{branch}` - Nom de la branche
- Version sémantique (si tags Git présents)

## Utilisation

### Développement Local

```bash
# 1. Copier le fichier .env d'exemple
cp .env.development .env

# 2. Modifier les valeurs si nécessaire
vim .env

# 3. Démarrer les services
docker-compose up -d

# 4. Lancer les tests localement
make test
```

### Déploiement Manuel

```bash
# Déclencher un déploiement manuel via gh CLI
gh workflow run cd.yaml -f environment=staging

# Ou via l'interface web:
# https://github.com/btall/core-africare-identity/actions/workflows/cd.yaml
```

### Surveillance des Workflows

```bash
# Lister les exécutions récentes
gh run list

# Voir les logs d'une exécution
gh run view {run-id} --log

# Surveiller une exécution en cours
gh run watch
```

## Bonnes Pratiques

1. **Ne jamais committer de secrets** - Toujours utiliser GitHub Secrets
2. **Tester localement avant de push** - Exécuter `make lint test` avant commit
3. **Utiliser des branches de feature** - Ne jamais push directement sur `main`
4. **Vérifier les logs CI** - S'assurer que tous les tests passent
5. **Valider les déploiements staging** - Tester sur staging avant production
6. **Monitorer les déploiements** - Vérifier le health check après déploiement

## Dépannage

### Le workflow CI échoue

```bash
# Vérifier les logs
gh run view {run-id} --log

# Reproduire localement
make lint
make test
docker build -t test .
```

### Le déploiement échoue

1. Vérifier que tous les secrets sont configurés
2. Vérifier les credentials Azure: `az login`
3. Vérifier les permissions du Service Principal
4. Consulter les logs Azure Container Apps

### Les secrets ne sont pas disponibles

```bash
# Lister les secrets configurés
gh secret list

# Lister les variables configurées
gh variable list

# Reconfigurer avec le script
./.github/scripts/setup-secrets.sh production
```

## Références

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [GitHub CLI Documentation](https://cli.github.com/manual/)
- [Azure Container Apps Deploy Action](https://github.com/Azure/container-apps-deploy-action)
- [Docker Build Push Action](https://github.com/docker/build-push-action)
