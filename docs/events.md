# Event System - Redis Pub/Sub

Ce service utilise **Redis Pub/Sub** pour la communication événementielle entre microservices (Phase 1 MVP).

## Table des Matières

- [Architecture](#architecture)
- [Configuration](#configuration)
- [Usage](#usage)
- [Limitations Phase 1](#limitations-phase-1)
- [Migration Phase 2](#migration-phase-2)
- [Troubleshooting](#troubleshooting)

## Architecture

### Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────┐
│                     Redis Pub/Sub                            │
│                   (redis://redis:6379)                       │
│                                                              │
│  Channels (topics):                                          │
│  ├─ identity.entity.created            │
│  ├─ identity.entity.updated            │
│  └─ identity.entity.deleted            │
└─────────────────────────────────────────────────────────────┘
          ↑ publish                      ↓ subscribe
┌──────────────────┐              ┌──────────────────┐
│  Service A       │              │  Service B       │
│  (Publisher)     │              │  (Subscriber)    │
└──────────────────┘              └──────────────────┘
```

### Principes Clés

1. **Simple et Gratuit** : Redis déjà disponible sur serveur local
2. **Pub/Sub Pattern** : Fire-and-forget, pas de garantie de livraison
3. **Faible Volume** : Adapté pour < 1000 messages/jour (Phase 1 MVP)
4. **Migration Prévue** : Passage à Azure Service Bus en Phase 2

## Configuration

### Variables d'Environnement

```bash
# Redis Configuration (Phase 1 MVP)
REDIS_URL=redis://localhost:6379
REDIS_DB=0

# Messaging Backend
MESSAGING_BACKEND=redis
```

### Fichier `.env`

```bash
# Redis Pub/Sub (Phase 1 MVP)
REDIS_URL=redis://redis:6379
REDIS_DB=0
```

### Configuration Docker Compose

Le fichier `docker-compose.yaml` inclut déjà un service Redis :

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

volumes:
  redis_data:
```

## Usage

### Publication d'Événements

#### Exemple Simple

```python
from app.core.events import publish

# Publier un événement
await publish("identity.patient.created", {
    "patient_id": "123",
    "name": "Jean Dupont",
    "timestamp": datetime.now(UTC).isoformat()
})
```

#### Avec Modèle Pydantic

```python
from app.core.events import publish
from app.schemas.events import PatientCreatedEvent

# Créer l'événement
event = PatientCreatedEvent(
    patient_id="123",
    name="Jean Dupont"
)

# Publier (conversion automatique en dict)
await publish("identity.patient.created", event)
```

#### Depuis un Endpoint

```python
from fastapi import APIRouter
from app.core.events import publish
from app.schemas.patient import PatientCreate, PatientResponse

router = APIRouter()

@router.post("/patients", response_model=PatientResponse)
async def create_patient(patient: PatientCreate):
    """Créer un nouveau patient."""
    # Logique métier
    created_patient = await patient_service.create(patient)

    # Publier événement
    await publish("identity.patient.created", {
        "patient_id": str(created_patient.id),
        "name": created_patient.name,
        "created_at": created_patient.created_at.isoformat()
    })

    return PatientResponse.model_validate(created_patient)
```

### Consommation d'Événements

#### Enregistrer un Handler

```python
from app.core.events import subscribe

@subscribe("user.created")
async def handle_user_created(payload: dict):
    """
    Handler pour les événements user.created d'autres services.

    Args:
        payload: Données de l'événement
            {
                "user_id": "123",
                "email": "user@example.com",
                "timestamp": "2025-01-15T10:30:00+00:00"
            }
    """
    user_id = payload.get("user_id")
    logger.info(f"Nouveau utilisateur créé: {user_id}")

    # Votre logique métier
    await initialize_patient_profile(user_id)
```

#### Handler avec Validation Pydantic

```python
from pydantic import BaseModel
from app.core.events import subscribe

class UserCreatedPayload(BaseModel):
    user_id: str
    email: str
    timestamp: str

@subscribe("user.created")
async def handle_user_created(payload: dict):
    """Handler avec validation."""
    try:
        # Valider le payload
        event = UserCreatedPayload(**payload)

        # Traiter l'événement
        await process_new_user(event.user_id, event.email)

    except ValidationError as e:
        logger.error(f"Payload invalide pour user.created: {e}")
```

### Retry et Resilience

Le système inclut un **retry automatique avec backoff exponentiel** :

```python
# Automatique dans publish()
await publish("event.subject", payload, max_retries=3)
# Tentatives: 1s, 2s, 4s entre chaque retry
```

## Limitations Phase 1

### Limitations Acceptées

Redis Pub/Sub présente les limitations suivantes, **acceptables pour Phase 1 MVP** :

1. **Pas de Persistence**
   - Événements perdus si aucun subscriber connecté
   - Pas de replay des événements passés
   - **Impact** : Acceptable avec volume < 1000 msg/jour

2. **Pas de Garantie de Livraison**
   - Fire-and-forget : pas de confirmation de réception
   - Pas de retry automatique côté broker
   - **Mitigation** : Retry dans `publish()` avec backoff exponentiel

3. **Pas de Consumer Groups**
   - Tous les subscribers reçoivent tous les messages
   - Pas de scaling horizontal des consumers
   - **Impact** : Acceptable en Phase 1 (faible volume)

4. **Pas de Dead Letter Queue**
   - Événements en erreur non sauvegardés
   - **Mitigation** : Logging détaillé + monitoring

### Mitigations Implémentées

1. **Idempotence des Handlers**

   ```python
   @subscribe("user.created")
   async def handle_user_created(payload: dict):
       user_id = payload.get("user_id")

       # Vérifier si déjà traité (idempotence)
       if await is_already_processed(user_id):
           logger.info(f"Événement déjà traité: {user_id}")
           return

       # Traiter normalement
       await process_new_user(user_id)
   ```

2. **Monitoring et Alertes**
   - OpenTelemetry traces pour chaque événement
   - Métriques : événements publiés, consommés, erreurs
   - Alertes si taux d'erreur > 5%

3. **Logging Structuré**

   ```python
   logger.info("Événement publié", extra={
       "subject": subject,
       "message_id": message_id,
       "timestamp": datetime.now(UTC).isoformat()
   })
   ```

## Migration Phase 2

### Quand Migrer vers Azure Service Bus

Critères de basculement :

- ✅ 10 structures actives
- ✅ Volume > 5000 messages/jour
- ✅ Incidents pertes messages > 1/mois
- ✅ Budget Phase 2 disponible (300€/mois)

### Plan de Migration

**Étape 1 : Créer Azure Service Bus Basic**

```bash
az servicebus namespace create \
  --name africare-servicebus \
  --resource-group africare-rg \
  --sku Basic \
  --location westeurope
```

**Étape 2 : Régénérer Services**

```bash
# Régénérer service avec messaging_backend=eventhub
cookiecutter cookiecutter-africare-microservice \
  --no-input \
  service_type=core \
  service_slug=identity \
  messaging_backend=eventhub \
  azure_eventhub_namespace=africare-servicebus.servicebus.windows.net
```

**Étape 3 : Déploiement Progressif (Blue-Green)**

1. Déployer nouvelle version avec Event Hub
2. Router 10% du trafic vers nouvelle version
3. Monitorer pendant 24h
4. Augmenter progressivement (25%, 50%, 100%)
5. Retirer ancienne version

**Étape 4 : Vérification**

- Aucun événement perdu durant migration
- Latence équivalente ou meilleure
- Coût conforme au budget Phase 2

### Comparaison Redis vs Event Hub

| Critère | Redis Pub/Sub (Phase 1) | Azure Event Hub (Phase 2+) |
|---------|-------------------------|----------------------------|
| **Coût/mois** | 0€ (inclus serveur) | ~20-30€ |
| **Garantie livraison** | ❌ Non | ✅ Oui (checkpoint store) |
| **Persistence** | ❌ Mémoire uniquement | ✅ Durable (7+ jours) |
| **Replay** | ❌ Non | ✅ Oui (offset) |
| **Scaling horizontal** | ⚠️ Limité | ✅ Partitions |
| **Volume max** | < 10k msg/jour | Millions msg/jour |
| **Latence** | < 5ms | < 50ms |
| **Complexité** | ✅ Simple | ⚠️ Moyenne |

## Troubleshooting

### Problème : Événements Non Reçus

**Symptôme** : Handler enregistré mais événements non traités

**Diagnostic** :

```bash
# Vérifier connexion Redis
redis-cli -h redis -p 6379 PING
# Réponse attendue : PONG

# Vérifier subscribers actifs
redis-cli -h redis -p 6379 PUBSUB NUMSUB identity.entity.created
# Doit afficher > 0

# Vérifier logs du service
docker-compose logs -f core-africare-identity
```

**Solutions** :

1. Vérifier que le service consumer est démarré
2. Vérifier que `start_consuming()` est appelé dans le lifespan
3. Vérifier que le handler est importé dans `app/services/event_service.py`

### Problème : Événements Dupliqués

**Symptôme** : Handler exécuté plusieurs fois pour le même événement

**Cause** : Plusieurs instances du service subscribed au même channel

**Solution** : Implémenter idempotence dans le handler (voir section Mitigations)

### Problème : Redis Déconnecté

**Symptôme** : Erreurs de connexion Redis

**Diagnostic** :

```bash
# Vérifier service Redis
docker-compose ps redis

# Vérifier logs Redis
docker-compose logs redis
```

**Solutions** :

1. Redémarrer service Redis : `docker-compose restart redis`
2. Vérifier configuration `REDIS_URL` dans `.env`
3. Vérifier firewall si Redis distant

### Debug Mode

Pour activer les logs détaillés :

```bash
# .env
OTEL_LOG_LEVEL=debug
DEBUG=true
```

Logs détaillés pour chaque publication/consommation :

```
DEBUG [app.core.events] Événement 'patient.created' publié avec ID: abc-123
DEBUG [app.core.events] Handler 'handle_patient_created' exécuté pour 'patient.created'
```

## OpenTelemetry Integration

Chaque événement génère automatiquement :

**Traces** :

- `publish.{subject}` - Publication d'événement
- `consume.{subject}` - Consommation d'événement

**Attributs** :

```python
{
    "messaging.system": "redis",
    "messaging.destination": "patient.created",
    "messaging.message.id": "abc-123",
    "handlers.executed": 2,
    "handlers.failed": 0
}
```

**Métriques** :

- `events_published_total` - Nombre d'événements publiés
- `events_consumed_total` - Nombre d'événements consommés
- `event_handler_duration_seconds` - Durée d'exécution des handlers

## Ressources

- [Redis Pub/Sub Documentation](https://redis.io/docs/interact/pubsub/)
- [redis-py Documentation](https://redis-py.readthedocs.io/)
- [AfriCare MVP Phase 1 Specifications](../../../docs/mvp1/)
- [Migration Guide Phase 2](../../../docs/mvp1/02-modification-event-system.md)

---

**Note** : Cette implémentation Redis Pub/Sub est optimisée pour la **Phase 1 MVP** avec volume faible. La migration vers Azure Service Bus est planifiée pour Phase 2 lorsque le volume et les besoins de garanties augmenteront.
