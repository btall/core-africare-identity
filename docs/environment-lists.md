# Gestion des Listes dans les Variables d'Environnement

## Vue d'ensemble

Les variables d'environnement sont toujours des chaînes de caractères. Pour passer des listes (comme `ALLOWED_ORIGINS`, `TRUSTED_HOSTS`, etc.), nous devons les sérialiser en chaîne et les désérialiser dans l'application.

## Formats Supportés

Notre configuration Pydantic supporte deux formats :

### 1. Format Virgules (Recommandé) ✅

```bash
# Simple et lisible
ALLOWED_ORIGINS=http://localhost:3000,https://api.exemple.com,https://app.exemple.com
TRUSTED_HOSTS=localhost,127.0.0.1,*.exemple.com
SUPPORTED_LOCALES=fr,en
```

**Avantages:**

- Simple à lire et écrire
- Compatible avec tous les outils (Docker, Kubernetes, Azure)
- Pas de problèmes d'échappement de caractères

**Inconvénients:**

- Ne fonctionne pas si vos valeurs contiennent des virgules

### 2. Format JSON

```bash
# Format JSON standard
ALLOWED_ORIGINS='["http://localhost:3000","https://api.exemple.com"]'
TRUSTED_HOSTS='["localhost","127.0.0.1","*.exemple.com"]'
```

**Avantages:**

- Gère les valeurs contenant des virgules
- Format standard reconnu

**Inconvénients:**

- Nécessite un échappement correct des guillemets
- Plus complexe à lire

## Exemples d'Utilisation

### Docker Compose

```yaml
services:
  mon-service:
    environment:
      # Format virgules
      ALLOWED_ORIGINS: "http://localhost:3000,https://app.africare.sn"
      TRUSTED_HOSTS: "localhost,127.0.0.1,*.africare.sn"

      # Format JSON (attention aux guillemets)
      # ALLOWED_ORIGINS: '["http://localhost:3000","https://app.africare.sn"]'
```

### Azure Container Apps (Bicep)

```bicep
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  properties: {
    template: {
      containers: [{
        env: [
          {
            name: 'ALLOWED_ORIGINS'
            value: 'https://app.africare.sn,https://admin.africare.sn'
          }
          {
            name: 'TRUSTED_HOSTS'
            value: '*.africare.sn,app.africare.sn'
          }
        ]
      }]
    }
  }
}
```

### Azure CLI

```bash
# Format virgules
az containerapp update \
  --name mon-app \
  --resource-group mon-rg \
  --set-env-vars \
    ALLOWED_ORIGINS="https://app.africare.sn,https://admin.africare.sn" \
    TRUSTED_HOSTS="*.africare.sn,app.africare.sn"
```

### Kubernetes

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  ALLOWED_ORIGINS: "https://app.africare.sn,https://admin.africare.sn"
  TRUSTED_HOSTS: "*.africare.sn,app.africare.sn"
```

### Fichier .env

```bash
# Development
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:4200
TRUSTED_HOSTS=localhost,127.0.0.1
SUPPORTED_LOCALES=fr,en

# Production
# ALLOWED_ORIGINS=https://app.africare.sn,https://admin.africare.sn
# TRUSTED_HOSTS=*.africare.sn,app.africare.sn
```

## Implémentation dans le Code

Le validateur Pydantic gère automatiquement la conversion :

```python
@field_validator("ALLOWED_ORIGINS", mode='before')
@classmethod
def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
    """Convertit une chaîne en liste selon le format."""
    if isinstance(v, list):
        return v
    elif isinstance(v, str):
        v = v.strip()
        # Format JSON
        if v.startswith("[") and v.endswith("]"):
            import json
            return json.loads(v)
        # Format virgules
        elif v:
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        else:
            return []
    raise ValueError(f"Format invalide: {v}")
```

## Recommandations

1. **Utilisez le format virgules** pour la simplicité
2. **Évitez les espaces** autour des virgules (ils seront supprimés automatiquement)
3. **Testez vos configurations** avec `make test` avant le déploiement
4. **Documentez vos choix** dans le README du projet
5. **Utilisez des secrets** pour les valeurs sensibles (ne pas les mettre dans les listes)

## Dépannage

### Erreur "Format JSON invalide"

```bash
# ❌ Mauvais - Guillemets mal échappés
ALLOWED_ORIGINS=["http://localhost:3000"]

# ✅ Correct - Guillemets simples autour
ALLOWED_ORIGINS='["http://localhost:3000"]'
```

### Liste vide inattendue

```bash
# ❌ Mauvais - Espaces seulement
ALLOWED_ORIGINS="   "

# ✅ Correct - Valeur vide ou liste explicite
ALLOWED_ORIGINS=""
# ou
ALLOWED_ORIGINS="http://localhost:3000"
```
