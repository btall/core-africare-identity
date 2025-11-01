# Filtrage des Événements Webhook par Client

Ce document explique la logique de filtrage des événements webhook Keycloak basée sur le `clientId` pour garantir que seuls les événements provenant des portails patient et professionnel sont synchronisés.

## Table des matières

- [Problématique](#problématique)
- [Solution implémentée](#solution-implémentée)
- [Règles de filtrage](#règles-de-filtrage)
- [Alignement avec la SPI Keycloak](#alignement-avec-la-spi-keycloak)
- [Types d'événements](#types-dévénements)
- [Cas d'usage](#cas-dusage)
- [Tests](#tests)
- [Monitoring](#monitoring)

## Problématique

### Contexte

Keycloak envoie des événements webhook pour **toutes** les actions utilisateur, qu'elles proviennent:

- Du **portail patient** (`apps-africare-patient-portal`)
- Du **portail professionnel** (`apps-africare-provider-portal`)
- De la **console admin** (`security-admin-console`, `apps-africare-admin-portal`)
- D'autres clients personnalisés

**Problème observé**:

Lorsqu'un administrateur modifiait un utilisateur via la console admin Keycloak, l'événement `UPDATE_PROFILE` était envoyé mais le traitement échouait avec l'erreur:

```
Patient or Professional not found
```

**Cause racine**:

Les administrateurs Keycloak ne sont ni des patients ni des professionnels de santé. Synchroniser leurs actions n'a pas de sens dans le contexte métier d'AfriCare.

## Solution implémentée

### Clients autorisés

Seuls les événements provenant des portails métier sont synchronisés:

```python
# app/services/webhook_processor.py
ALLOWED_CLIENT_IDS = {
    "apps-africare-patient-portal",
    "apps-africare-provider-portal",
}
```

### Logique de filtrage

```python
async def route_webhook_event(db: AsyncSession, event: KeycloakWebhookEvent) -> SyncResult:
    # 1. Filtrer TOUS les événements avec préfixe ADMIN_*
    if event.event_type.startswith("ADMIN_"):
        return SyncResult(
            success=True,
            message="Événement admin console ignoré: {event.event_type}"
        )

    # 2. Exception: DELETE peut avoir clientId=null (suppression admin console)
    #    DELETE doit TOUJOURS être synchronisé pour maintenir cohérence des données
    if event.event_type == "DELETE":
        # Traiter DELETE même si clientId non autorisé
        return await handler(db, event)

    # 3. Filtrer événements normaux par clientId autorisé
    if event.client_id and event.client_id not in ALLOWED_CLIENT_IDS:
        return SyncResult(
            success=True,  # success=True pour ACK le message (pas un échec)
            message=f"Événement ignoré: clientId {event.client_id} non autorisé"
        )

    # 4. Traiter avec le handler approprié
    handler = EVENT_HANDLERS.get(event.event_type)
    return await handler(db, event)
```

## Règles de filtrage

### Tableau récapitulatif

| Type Événement | clientId | Comportement | Raison |
|---------------|----------|--------------|---------|
| **ADMIN_UPDATE** | any/null | **Ignoré** | Console admin Keycloak |
| **ADMIN_*** | any | **Ignoré** | Tous événements admin |
| **DELETE** | null | **Traité** | Suppression admin légitime |
| **DELETE** | autorisé | **Traité** | Suppression patient/pro |
| **DELETE** | non autorisé | **Traité** | Sync suppressions admin |
| **REGISTER** | autorisé | **Traité** | Inscription portail |
| **REGISTER** | non autorisé | **Ignoré** | Admin console |
| **REGISTER** | null | **Traité** | Backward compatibility |
| **UPDATE_PROFILE** | autorisé | **Traité** | Mise à jour portail |
| **UPDATE_PROFILE** | non autorisé | **Ignoré** | Admin console |
| **LOGIN** | autorisé | **Traité** | Tracking connexion |
| **LOGIN** | non autorisé | **Ignoré** | Connexion admin |

### Pourquoi DELETE est toujours traité?

Les événements DELETE doivent **toujours** être synchronisés pour maintenir la cohérence des données:

1. **Suppression par admin**: Un admin supprime un patient/professionnel depuis la console
   - `clientId` peut être `null` ou `security-admin-console`
   - Doit quand même synchroniser pour marquer l'utilisateur comme supprimé

2. **Suppression auto**: Patient supprime son propre compte
   - `clientId` = `apps-africare-patient-portal`
   - Doit synchroniser normalement

3. **Intégrité RGPD**: Le droit à l'oubli impose la synchronisation des suppressions

**Implémentation**:

```python
# Exception explicite pour DELETE
if event.event_type != "DELETE" and event.client_id and event.client_id not in ALLOWED_CLIENT_IDS:
    # Filtrer sauf DELETE
    return SyncResult(success=True, message="Ignoré")

# DELETE passe le filtre et est traité
```

## Alignement avec la SPI Keycloak

### Analyse du provider Java

Le provider Keycloak (`WebhookEventListenerProvider.java`) envoie deux types d'événements:

#### 1. Événements utilisateur normaux (lines 50-95)

```java
// Monitored events
private static final Set<EventType> MONITORED_EVENTS = EnumSet.of(
    EventType.REGISTER,
    EventType.LOGIN,
    EventType.UPDATE_EMAIL,
    EventType.UPDATE_PROFILE,
    EventType.VERIFY_EMAIL,
    EventType.LOGOUT
);

// Toujours avec clientId
String clientId = event.getClientId();
payload.put("clientId", clientId);
```

**Caractéristiques**:

- Déclenchés par actions utilisateur (portail patient, professionnel, admin)
- `clientId` **toujours présent** depuis `event.getClientId()`
- Permettent de distinguer l'origine de l'action

#### 2. Événements admin console (lines 98-136)

```java
@Override
public void onEvent(AdminEvent adminEvent, boolean includeRepresentation) {
    if (adminEvent.getOperationType() == OperationType.UPDATE) {
        // IMPORTANT: eventType = "ADMIN_UPDATE" (line 184)
        payload.put("eventType", "ADMIN_" + adminEvent.getOperationType());
    }
    else if (adminEvent.getOperationType() == OperationType.DELETE) {
        // IMPORTANT: eventType = "DELETE" (line 236) - PAS "ADMIN_DELETE"
        payload.put("eventType", "DELETE");
    }

    // clientId extrait depuis authDetails (peut être null)
    String clientId = null;
    if (adminEvent.getAuthDetails() != null) {
        clientId = adminEvent.getAuthDetails().getClientId();
    }
    payload.put("clientId", clientId);
}
```

**Caractéristiques**:

- Déclenchés par actions admin console
- `eventType` = `"ADMIN_UPDATE"` pour UPDATE (préfixe ADMIN_)
- `eventType` = `"DELETE"` pour DELETE (PAS de préfixe ADMIN_)
- `clientId` peut être **null** ou `security-admin-console`

### Schéma Pydantic aligné

```python
# app/schemas/keycloak.py
class KeycloakWebhookEvent(BaseModel):
    event_type: Literal[
        # Événements utilisateur normaux
        "REGISTER",
        "UPDATE_PROFILE",
        "UPDATE_EMAIL",
        "LOGIN",
        "VERIFY_EMAIL",      # Ajouté
        "LOGOUT",            # Ajouté
        # Événements admin console
        "ADMIN_UPDATE",      # Ajouté
        "DELETE",            # PAS "ADMIN_DELETE"
    ]
    client_id: str | None  # Peut être null pour admin events
```

## Types d'événements

### Événements synchronisés

#### REGISTER

- **Source**: Portail patient/professionnel
- **Action**: Création d'un nouveau profil Patient/Professional
- **Filtrage**: Par clientId autorisé

```python
# Événement accepté
{
    "eventType": "REGISTER",
    "clientId": "apps-africare-patient-portal",
    "userId": "user-123",
    "user": {...}
}

# Événement ignoré (admin console)
{
    "eventType": "REGISTER",
    "clientId": "security-admin-console",
    "userId": "admin-456",
    "user": {...}
}
```

#### UPDATE_PROFILE

- **Source**: Portail patient/professionnel ou admin console
- **Action**: Mise à jour du profil
- **Filtrage**: Par clientId autorisé

#### UPDATE_EMAIL

- **Source**: Portail patient/professionnel
- **Action**: Changement d'adresse email
- **Filtrage**: Par clientId autorisé

#### LOGIN

- **Source**: Tous les portails
- **Action**: Tracking connexion (pas de modification DB)
- **Filtrage**: Par clientId autorisé

#### DELETE

- **Source**: Admin console ou portail (auto-suppression)
- **Action**: Suppression/anonymisation du profil
- **Filtrage**: **AUCUN** (toujours traité)

### Événements ignorés

#### ADMIN_UPDATE

- **Source**: Console admin Keycloak
- **Action**: Modification admin (attributs, rôles, etc.)
- **Filtrage**: **Toujours ignoré** (préfixe ADMIN_)

```python
{
    "eventType": "ADMIN_UPDATE",
    "clientId": "security-admin-console",  # ou null
    "userId": "user-789",
    "user": {...}
}
```

**Raison**: Les modifications admin Keycloak ne correspondent pas forcément à des changements métier (ex: modification de groupes, réinitialisation de mot de passe).

#### VERIFY_EMAIL, LOGOUT

- **Source**: Portails divers
- **Action**: Vérification email, déconnexion
- **Filtrage**: Par clientId autorisé
- **Note**: Handlers pas encore implémentés (TODO)

## Cas d'usage

### Cas 1: Inscription patient via portail

**Scenario**:

1. Patient s'inscrit sur `apps-africare-patient-portal`
2. Keycloak envoie webhook `REGISTER` avec `clientId=apps-africare-patient-portal`
3. Événement **traité** → Patient créé dans PostgreSQL

**Webhook payload**:

```json
{
  "eventType": "REGISTER",
  "clientId": "apps-africare-patient-portal",
  "userId": "abc-123",
  "user": {
    "firstName": "Amadou",
    "lastName": "Diallo",
    "email": "amadou@example.sn",
    "dateOfBirth": "1990-05-15",
    "gender": "male"
  }
}
```

**Résultat**:

```python
SyncResult(
    success=True,
    event_type="REGISTER",
    patient_id=42,
    message="Patient created: 42"
)
```

### Cas 2: Admin modifie un utilisateur via console

**Scenario**:

1. Admin modifie attributs via console Keycloak
2. Keycloak envoie webhook `ADMIN_UPDATE` avec `clientId=security-admin-console`
3. Événement **ignoré** → Aucune action

**Webhook payload**:

```json
{
  "eventType": "ADMIN_UPDATE",
  "clientId": "security-admin-console",
  "userId": "def-456",
  "user": {
    "firstName": "Fatou",
    "lastName": "Sow",
    "email": "fatou@example.sn",
    "enabled": true
  }
}
```

**Résultat**:

```python
SyncResult(
    success=True,  # Success pour ACK message
    event_type="ADMIN_UPDATE",
    message="Événement admin console ignoré: ADMIN_UPDATE"
)
```

### Cas 3: Admin supprime un patient via console

**Scenario**:

1. Admin supprime utilisateur via console Keycloak
2. Keycloak envoie webhook `DELETE` avec `clientId=null` ou `security-admin-console`
3. Événement **traité** → Patient marqué comme supprimé/anonymisé

**Webhook payload**:

```json
{
  "eventType": "DELETE",
  "clientId": null,
  "userId": "ghi-789",
  "user": {
    "id": "ghi-789",
    "deleted": true,
    "deletionTime": 1704067200000
  }
}
```

**Résultat**:

```python
SyncResult(
    success=True,
    event_type="DELETE",
    patient_id=123,
    message="Patient deleted/anonymized: 123"
)
```

### Cas 4: Application custom tente d'inscrire un utilisateur

**Scenario**:

1. Application non autorisée envoie événement
2. Keycloak envoie webhook `REGISTER` avec `clientId=custom-app`
3. Événement **ignoré** → Aucune action

**Webhook payload**:

```json
{
  "eventType": "REGISTER",
  "clientId": "custom-app",
  "userId": "xyz-999",
  "user": {...}
}
```

**Résultat**:

```python
SyncResult(
    success=True,  # Success pour ACK message
    message="Événement ignoré: clientId custom-app non autorisé (admin)"
)
```

## Tests

### Suite de tests complète

Le fichier `tests/test_webhook_client_filtering.py` contient **15 tests** couvrant tous les cas:

#### Tests positifs (traitement)

1. `test_allowed_client_patient_portal`: Login patient traité
2. `test_allowed_client_provider_portal`: Login professionnel traité
3. `test_null_client_id_treated_as_allowed`: clientId null traité
4. `test_delete_with_null_client_id_is_processed`: DELETE null traité
5. `test_delete_with_allowed_client_is_processed`: DELETE autorisé traité
6. `test_delete_event_from_admin_client_is_processed`: DELETE admin traité

#### Tests négatifs (filtrage)

7. `test_disallowed_client_admin_portal`: Admin portal ignoré
8. `test_disallowed_client_custom_app`: App custom ignorée
9. `test_disallowed_client_register_event`: REGISTER admin ignoré
10. `test_admin_update_event_ignored`: ADMIN_UPDATE ignoré
11. `test_admin_update_with_null_client_id`: ADMIN_UPDATE null ignoré
12. `test_admin_update_prefix_always_ignored`: Préfixe ADMIN_* ignoré

#### Tests de validation

13. `test_allowed_clients_constant`: Vérification constante
14. `test_case_sensitive_client_id`: Sensibilité casse
15. `test_disallowed_client_event_attributes_set`: Attributs OpenTelemetry

### Exécution des tests

```bash
# Tests de filtrage uniquement
poetry run pytest tests/test_webhook_client_filtering.py -v

# Tous les tests unitaires
poetry run pytest tests/ -v -m "not integration"
```

**Résultats attendus**:

```
tests/test_webhook_client_filtering.py::...::test_allowed_client_patient_portal PASSED
tests/test_webhook_client_filtering.py::...::test_admin_update_event_ignored PASSED
...
============================== 15 passed in 0.31s ==============================
```

## Monitoring

### OpenTelemetry spans

Chaque événement ignoré génère un span OpenTelemetry avec contexte:

```python
span.set_attribute("event.type", event.event_type)
span.set_attribute("event.client_id", event.client_id or "null")
span.add_event(
    "Événement ignoré: client non autorisé",
    {"client_id": event.client_id, "allowed_clients": ", ".join(ALLOWED_CLIENT_IDS)}
)
```

### Logs structurés

```python
logger.info(
    f"Événement ignoré: clientId={event.client_id} non autorisé "
    f"(autorisés: {', '.join(ALLOWED_CLIENT_IDS)}). "
    f"Type={event.event_type}, user_id={event.user_id}"
)
```

### Métriques Prometheus

Les événements ignorés sont comptabilisés dans les métriques webhook:

```python
webhook_events_acked_total{event_type="UPDATE_PROFILE", result="ignored"}
webhook_events_acked_total{event_type="ADMIN_UPDATE", result="ignored"}
```

**Requête Prometheus recommandée**:

```promql
# Taux d'événements ignorés par type
rate(webhook_events_acked_total{result="ignored"}[5m])

# Ratio événements ignorés / traités
sum(rate(webhook_events_acked_total{result="ignored"}[5m]))
/
sum(rate(webhook_events_acked_total[5m]))
```

### Dashboard Grafana

Panneaux recommandés:

1. **Événements par clientId** (gauge)
2. **Taux d'événements ignorés** (graph)
3. **Top clientIds non autorisés** (table)
4. **Événements ADMIN_UPDATE ignorés** (counter)

## Références

- [SPI Keycloak](../../keycloak/spi/keycloak-webhook-listener/src/main/java/app/africare/keycloak/WebhookEventListenerProvider.java)
- [Webhook Processor](../app/services/webhook_processor.py)
- [Schémas Keycloak](../app/schemas/keycloak.py)
- [Tests de Filtrage](../tests/test_webhook_client_filtering.py)
- [Synchronisation Webhook](./webhook-synchronization.md)
- [Validation Temporelle](./webhook-timestamp-validation.md)
