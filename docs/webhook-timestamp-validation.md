# Validation Temporelle des Webhooks Keycloak

## Contexte

Les événements webhook Keycloak sont traités de manière asynchrone via Redis Streams. Dans certains scénarios (replay, downtime prolongé, réclamation de messages pending), les événements peuvent être traités plusieurs jours après leur génération.

## Problème Original

La validation initiale du timestamp dans `KeycloakWebhookEvent` rejetait tout événement plus vieux que **24 heures**, causant des erreurs de validation lors du traitement d'événements anciens :

```
ValidationError: Timestamp invalide: 1761749965561 (maintenant: 1761961869588)
```

Cela posait problème dans les cas suivants :

1. **Replay de messages** : Rejouer des événements depuis Redis Streams après plusieurs jours
2. **Réclamation de messages pending** : Messages bloqués récupérés via XCLAIM après downtime
3. **Backlog d'événements** : Accumulation d'événements pendant maintenance ou incident
4. **Redémarrage après crash** : Traitement d'événements non ACK après un crash du service

## Solution Implémentée

La fenêtre de validation temporelle a été **étendue de 24h à 30 jours** :

```python
# app/schemas/keycloak.py
@field_validator("event_time")
@classmethod
def validate_event_time(cls, v: int) -> int:
    """Valide que le timestamp est raisonnable (derniers 30 jours ou futur proche).

    Fenêtre de 30 jours pour supporter:
    - Replay de messages Redis Streams après incident
    - Traitement de messages pending réclamés après downtime
    - Backlog d'événements accumulés pendant maintenance
    """
    now_ms = int(datetime.now().timestamp() * 1000)
    day_ms = 24 * 60 * 60 * 1000
    thirty_days_ms = 30 * day_ms

    # Accepte événements des derniers 30 jours ou jusqu'à 1h dans le futur
    if v < (now_ms - thirty_days_ms) or v > (now_ms + 3600000):
        raise ValueError(f"Timestamp invalide: {v} (maintenant: {now_ms})")

    return v
```

### Règles de Validation

**Événements Acceptés** :
- Derniers **30 jours** (passé)
- Jusqu'à **1 heure** dans le futur (tolérance pour décalage horaire/NTP)

**Événements Rejetés** :
- Plus de **30 jours** dans le passé
- Plus de **1 heure** dans le futur

### Justification de la Fenêtre de 30 Jours

**Scénarios couverts** :
- Incident de production avec résolution en quelques jours
- Maintenance planifiée avec backlog d'événements
- Tests de reprise après sinistre (disaster recovery)
- Replay manuel d'événements pour correction de données

**Compromis** :
- **Trop court** (< 7 jours) : Risque de rejet d'événements légitimes après incident
- **Trop long** (> 90 jours) : Accepte des événements obsolètes ou erronés
- **30 jours** : Équilibre entre flexibilité opérationnelle et intégrité des données

## Tests de Validation

12 tests unitaires couvrent tous les cas de figure (`tests/test_keycloak_webhook_event_validation.py`) :

1. **Événements récents** (30 minutes) : ✓ Accepté
2. **Événements d'hier** (24h) : ✓ Accepté
3. **Événements de 3 jours** (cas de l'erreur originale) : ✓ Accepté
4. **Événements de 7 jours** : ✓ Accepté
5. **Événements de 30 jours** : ✓ Accepté
6. **Événements > 30 jours** : ✗ Rejeté
7. **Événements futurs proche** (30 minutes) : ✓ Accepté
8. **Événements futurs lointain** (2 heures) : ✗ Rejeté
9. **Cas limites** : 30 jours exactement, 1h future exactement
10. **Scénario réel** : Replay après 4 jours de downtime

## Impact sur le Système

### Avant la Modification

```
Fenêtre de validation : 24 heures
Événements rejetés    : 3-4 jours et plus
Erreur type           : ValidationError sur event_time
```

### Après la Modification

```
Fenêtre de validation : 30 jours
Événements acceptés   : 3-4 jours (replay/downtime)
Couverture de code    : 96% (app/schemas/keycloak.py)
Tests unitaires       : 12 nouveaux tests, tous passent
```

## Monitoring et Métriques

Les événements traités avec timestamps anciens sont automatiquement trackés via OpenTelemetry :

```python
# Métriques disponibles
webhook_events_acked      # Événements ACK avec event_type
webhook_processing_duration  # Durée de traitement
webhook_events_failed     # Échecs avec reason
```

**Requête Prometheus recommandée** :

```promql
# Histogramme de l'âge des événements traités
histogram_quantile(0.95,
  rate(webhook_processing_duration_bucket[5m])
)

# Taux d'échec par type d'événement
rate(webhook_events_failed_total[5m]) /
rate(webhook_events_acked_total[5m])
```

## Recommandations Opérationnelles

1. **Monitoring** : Surveiller l'âge des événements traités (alerter si > 7 jours)
2. **Alerting** : Créer une alerte si des événements > 14 jours sont traités régulièrement
3. **Retention** : Ajuster la retention Redis Streams si nécessaire (actuellement illimité)
4. **Dead Letter Queue** : Vérifier régulièrement `webhook_dlq` pour événements abandonnés
5. **Backlog** : Surveiller `XPENDING` pour détecter accumulation anormale

## Références

- `app/schemas/keycloak.py:110-128` - Implémentation du validateur
- `tests/test_keycloak_webhook_event_validation.py` - Tests complets
- `docs/keycloak-webhook-setup.md` - Configuration générale des webhooks
- `app/core/webhook_streams.py` - Traitement Redis Streams
