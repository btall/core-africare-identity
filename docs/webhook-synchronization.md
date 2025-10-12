# Synchronisation Keycloak par Webhooks

Ce document explique le système de synchronisation temps-réel entre Keycloak et PostgreSQL via webhooks.

## Vue d'ensemble

Le service `core-africare-identity` implémente un système de synchronisation temps-réel qui écoute les événements Keycloak via webhooks et met à jour automatiquement la base de données PostgreSQL locale.

### Architecture

```
┌─────────────┐         Webhook Events          ┌──────────────────────────┐
│             │  ────────────────────────────►  │                          │
│  Keycloak   │   (HMAC-SHA256 signed)          │ core-africare-identity   │
│             │                                  │                          │
└─────────────┘                                  └──────────────────────────┘
                                                          │
                                                          ▼
                                                    PostgreSQL
                                                   (Patients DB)
```

### Événements Supportés

| Événement       | Description                                | Action                          |
|-----------------|--------------------------------------------|---------------------------------|
| `REGISTER`      | Nouvel utilisateur enregistré sur Keycloak | Crée un profil Patient/Professional |
| `UPDATE_PROFILE`| Mise à jour du profil utilisateur          | Met à jour Patient/Professional  |
| `UPDATE_EMAIL`  | Changement d'adresse email                 | Met à jour l'email du Patient    |
| `LOGIN`         | Connexion utilisateur                      | Tracking/Analytics uniquement    |

## Endpoints API

### POST /api/v1/webhooks/keycloak

Reçoit les événements webhook de Keycloak.

**Headers requis:**
```http
Content-Type: application/json
X-Keycloak-Signature: <hmac-sha256-hex>
X-Keycloak-Timestamp: <unix-timestamp>
```

**Request Body:**
```json
{
  "type": "REGISTER",
  "realmId": "africare",
  "clientId": "core-africare-identity",
  "userId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "ipAddress": "192.168.1.1",
  "sessionId": "session-uuid",
  "details": {
    "username": "amadou.diallo",
    "email": "amadou.diallo@example.sn",
    "first_name": "Amadou",
    "last_name": "Diallo",
    "date_of_birth": "1990-05-15",
    "gender": "male",
    "phone": "+221771234567",
    "country": "Sénégal",
    "preferred_language": "fr"
  },
  "time": 1234567890000
}
```

**Response (200 OK):**
```json
{
  "success": true,
  "event_type": "REGISTER",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "patient_id": 42,
  "message": "Patient created: 42",
  "synced_at": "2025-01-15T10:30:00Z"
}
```

**Error Responses:**
- `400 Bad Request`: Headers manquants ou payload invalide
- `401 Unauthorized`: Signature webhook invalide
- `500 Internal Server Error`: Erreur lors du traitement

### GET /api/v1/webhooks/keycloak/health

Vérifie l'état de santé du webhook endpoint.

**Response:**
```json
{
  "status": "healthy",
  "webhook_endpoint": "/api/v1/webhooks/keycloak",
  "last_event_received": "2025-01-15T10:30:00Z",
  "total_events_processed": 1234,
  "failed_events_count": 5
}
```

**Status Values:**
- `healthy`: < 10% d'échecs
- `degraded`: 10-50% d'échecs
- `unhealthy`: > 50% d'échecs

## Sécurité

### Vérification de Signature HMAC-SHA256

Toutes les requêtes webhook doivent être signées avec HMAC-SHA256.

**Algorithme:**
```python
signature = hmac_sha256(secret, f"{timestamp}.{payload}")
```

**Configuration:**
```bash
# Secret partagé (générer avec: openssl rand -hex 32)
WEBHOOK_SECRET=your-64-char-hex-secret

# Tolérance du timestamp (5 minutes par défaut)
WEBHOOK_SIGNATURE_TOLERANCE=300
```

**Vérification:**
1. Extraire `X-Keycloak-Signature` et `X-Keycloak-Timestamp`
2. Vérifier que le timestamp est dans la fenêtre de tolérance (± 5 min)
3. Calculer la signature attendue avec le secret
4. Comparer avec `hmac.compare_digest()` (protection timing attacks)

### Protection Contre les Attaques

- **Replay Protection**: Tolérance timestamp de 5 minutes
- **Timing Attacks**: Utilisation de `hmac.compare_digest()`
- **Rate Limiting**: Configuré au niveau du reverse proxy
- **HTTPS Only**: Communication chiffrée obligatoire

## Logique de Synchronisation

### 1. REGISTER Event

Crée un nouveau profil Patient dans PostgreSQL:

```python
@subscribe("REGISTER")
async def sync_user_registration(db: AsyncSession, event: KeycloakWebhookEvent):
    # Vérifier si l'utilisateur existe déjà
    existing = await db.execute(
        select(Patient).where(Patient.keycloak_user_id == event.user_id)
    )
    if existing.scalar_one_or_none():
        return SyncResult(success=True, message="User already synchronized")

    # Créer le patient
    patient = Patient(
        keycloak_user_id=event.user_id,
        first_name=event.details.first_name,
        last_name=event.details.last_name,
        date_of_birth=date.fromisoformat(event.details.date_of_birth),
        gender=event.details.gender,
        email=event.details.email,
        phone=event.details.phone,
        country=event.details.country or "Sénégal",
        preferred_language=event.details.preferred_language or "fr",
        is_active=True
    )
    db.add(patient)
    await db.commit()

    # Publier événement pour autres services
    await publish("identity.patient.created", {
        "patient_id": patient.id,
        "keycloak_user_id": event.user_id
    })
```

**Champs requis dans Keycloak:**
- `first_name`, `last_name`: Nom complet
- `date_of_birth`: Format ISO (YYYY-MM-DD)
- `gender`: "male" ou "female"

**Champs optionnels:**
- `email`, `phone`, `national_id`
- `country`, `region`, `city`
- `preferred_language`

### 2. UPDATE_PROFILE Event

Met à jour les informations du Patient:

```python
@subscribe("UPDATE_PROFILE")
async def sync_profile_update(db: AsyncSession, event: KeycloakWebhookEvent):
    # Récupérer le patient
    result = await db.execute(
        select(Patient).where(Patient.keycloak_user_id == event.user_id)
    )
    patient = result.scalar_one_or_none()

    if not patient:
        return SyncResult(success=False, message="Patient not found")

    # Mettre à jour les champs modifiés
    updated_fields = []
    if event.details.first_name:
        patient.first_name = event.details.first_name
        updated_fields.append("first_name")

    if event.details.last_name:
        patient.last_name = event.details.last_name
        updated_fields.append("last_name")

    patient.updated_at = datetime.now()
    await db.commit()

    # Publier événement
    await publish("identity.patient.updated", {
        "patient_id": patient.id,
        "updated_fields": updated_fields
    })
```

### 3. UPDATE_EMAIL Event

Met à jour l'email du Patient:

```python
@subscribe("UPDATE_EMAIL")
async def sync_email_update(db: AsyncSession, event: KeycloakWebhookEvent):
    # Récupérer le patient
    result = await db.execute(
        select(Patient).where(Patient.keycloak_user_id == event.user_id)
    )
    patient = result.scalar_one_or_none()

    if not patient:
        return SyncResult(success=False, message="Patient not found")

    # Mettre à jour email
    old_email = patient.email
    patient.email = event.details.email
    patient.is_verified = event.details.email_verified or False
    patient.updated_at = datetime.now()
    await db.commit()

    # Publier événement
    await publish("identity.patient.email_updated", {
        "patient_id": patient.id,
        "old_email": old_email,
        "new_email": event.details.email
    })
```

### 4. LOGIN Event

Tracking uniquement (pas de modification DB):

```python
@subscribe("LOGIN")
async def track_user_login(db: AsyncSession, event: KeycloakWebhookEvent):
    # Publier événement pour analytics
    await publish("identity.user.login", {
        "keycloak_user_id": event.user_id,
        "ip_address": event.ip_address,
        "session_id": event.session_id,
        "timestamp": event.timestamp_datetime.isoformat()
    })
```

## Retry Mechanism

Le système implémente un retry avec backoff exponentiel pour gérer les erreurs transitoires:

### Configuration

```python
@async_retry_with_backoff(
    max_attempts=3,           # 3 tentatives maximum
    min_wait_seconds=1,       # Attente initiale: 1 seconde
    max_wait_seconds=10,      # Attente maximale: 10 secondes
    exceptions=(              # Erreurs qui déclenchent un retry
        OperationalError,     # Connexion DB perdue
        DBAPIError,          # Erreurs DB génériques
    )
)
async def sync_user_registration(...):
    ...
```

### Backoff Exponentiel

- **Tentative 1**: Exécution immédiate
- **Tentative 2**: Attente 1 seconde
- **Tentative 3**: Attente 2 secondes (ou moins si échec rapide)

### Erreurs Non-Retryables

Ces erreurs échouent immédiatement (fail fast):
- `ValueError`: Données invalides
- `IntegrityError`: Contraintes DB violées
- Autres exceptions métier

## Observabilité

### OpenTelemetry Tracing

Chaque webhook génère automatiquement un span OpenTelemetry:

```python
with tracer.start_as_current_span("receive_keycloak_webhook") as span:
    span.set_attribute("event.type", event.type)
    span.set_attribute("event.user_id", event.user_id)
    span.set_attribute("sync.success", result.success)
```

**Attributs trackés:**
- `event.type`: Type d'événement
- `event.user_id`: UUID Keycloak
- `event.realm_id`: Realm Keycloak
- `sync.success`: Succès de la synchronisation
- `patient.id`: ID du patient créé/mis à jour

### Logging Structuré

```python
logger.info(
    f"Événement webhook reçu: type={event.type}, "
    f"user_id={event.user_id}, realm={event.realm_id}"
)

logger.warning(
    f"Retry attempt {attempt_number} after {seconds_since_start:.2f}s "
    f"for {function_name} - Exception: {exception}"
)
```

### Métriques

- **Total événements traités**: Compteur global
- **Échecs**: Compteur d'erreurs
- **Latence**: Temps de traitement par événement
- **Health status**: healthy/degraded/unhealthy

## Configuration Keycloak

Voir le document détaillé: [docs/keycloak-webhook-setup.md](./keycloak-webhook-setup.md)

### Résumé

1. **Activer les événements** dans le realm `africare`
2. **Installer le plugin webhook** (custom Java provider)
3. **Configurer les attributs personnalisés** (date_of_birth, gender, etc.)
4. **Définir le webhook URL** et le secret partagé

### Variables d'Environnement

```bash
# Dans Keycloak (plugin)
WEBHOOK_URL=https://identity.africare.sn/api/v1/webhooks/keycloak
WEBHOOK_SECRET=your-webhook-secret

# Dans core-africare-identity
WEBHOOK_SECRET=your-webhook-secret
WEBHOOK_SIGNATURE_TOLERANCE=300
```

## Tests

### Test Manuel

```bash
# Générer une signature de test
SECRET="your-webhook-secret"
TIMESTAMP=$(date +%s)
PAYLOAD='{"type":"REGISTER","realmId":"africare","userId":"test-123","time":1234567890000,"details":{"first_name":"Test","last_name":"User","email":"test@example.com","date_of_birth":"1990-01-01","gender":"male"}}'

# Calculer la signature
SIGNATURE=$(echo -n "${TIMESTAMP}.${PAYLOAD}" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')

# Envoyer le webhook
curl -X POST http://localhost:8001/api/v1/webhooks/keycloak \
  -H "Content-Type: application/json" \
  -H "X-Keycloak-Signature: $SIGNATURE" \
  -H "X-Keycloak-Timestamp: $TIMESTAMP" \
  -d "$PAYLOAD"
```

### Tests Unitaires

Voir `tests/test_webhook_signature.py` et `tests/test_keycloak_sync.py` (à créer).

### Health Check

```bash
curl http://localhost:8001/api/v1/webhooks/keycloak/health
```

## Troubleshooting

### Signature Invalide (401)

**Cause**: Secret webhook incorrect ou timestamp expiré

**Solution**:
1. Vérifier que `WEBHOOK_SECRET` est identique dans Keycloak et le service
2. Vérifier l'horloge système (NTP synchronization)
3. Augmenter `WEBHOOK_SIGNATURE_TOLERANCE` si nécessaire

### Patient Non Trouvé (404)

**Cause**: Événement `UPDATE_PROFILE` ou `UPDATE_EMAIL` reçu sans `REGISTER`

**Solution**:
1. Vérifier que Keycloak envoie bien `REGISTER` en premier
2. Créer manuellement le patient via l'API REST si nécessaire

### Données Manquantes (400)

**Cause**: Attributs requis absents dans Keycloak

**Solution**:
Configurer les attributs utilisateur dans Keycloak User Profile:
- `first_name`, `last_name` (Required)
- `date_of_birth` (Required, Validator: date format YYYY-MM-DD)
- `gender` (Required, Validator: options [male, female])

### Performance Dégradée

**Cause**: Trop d'événements, retry fréquents, DB lente

**Solution**:
1. Vérifier la santé de PostgreSQL
2. Augmenter les connexions DB si nécessaire
3. Monitorer les métriques OpenTelemetry
4. Vérifier les logs pour identifier les erreurs récurrentes

## Événements Publiés

Le service publie ces événements vers Redis Pub/Sub pour consommation par d'autres services:

| Événement                     | Payload                                         |
|-------------------------------|-------------------------------------------------|
| `identity.patient.created`    | `{patient_id, keycloak_user_id, email}`        |
| `identity.patient.updated`    | `{patient_id, keycloak_user_id, updated_fields}` |
| `identity.patient.email_updated` | `{patient_id, old_email, new_email}`        |
| `identity.user.login`         | `{keycloak_user_id, ip_address, session_id}`  |

## Références

- [Configuration Keycloak](./keycloak-webhook-setup.md)
- [Schémas Pydantic](../app/schemas/keycloak.py)
- [Service de Synchronisation](../app/services/keycloak_sync_service.py)
- [Endpoint Webhook](../app/api/v1/endpoints/webhooks.py)
- [Module de Sécurité](../app/core/webhook_security.py)
- [Module de Retry](../app/core/retry.py)
