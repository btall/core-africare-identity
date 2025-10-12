# Configuration Keycloak pour Webhooks

Ce document explique comment configurer Keycloak pour envoyer des webhooks vers `core-africare-identity` pour la synchronisation temps-réel.

## Architecture

```
┌─────────────┐         Webhook Events          ┌──────────────────────────┐
│             │  ────────────────────────────►  │                          │
│  Keycloak   │   (HMAC-SHA256 signed)          │ core-africare-identity   │
│             │  ◄────────────────────────────  │                          │
└─────────────┘     200 OK / Error              └──────────────────────────┘
      │                                                     │
      │                                                     │
      ▼                                                     ▼
  Event Store                                         PostgreSQL
  (Audit Log)                                        (Patients DB)
```

## Prérequis

- Keycloak 17+ installé et configuré
- Realm `africare` créé
- Accès admin au realm
- Le service `core-africare-identity` déployé et accessible depuis Keycloak

## 1. Configuration des Event Listeners

### Via Admin UI

1. Se connecter à l'admin console Keycloak
2. Sélectionner le realm `africare`
3. Aller dans **Realm Settings** > **Events**
4. Activer les événements:
   - **Event Listeners**: Ajouter `jboss-logging` et `custom-webhook-listener`
   - **Save Events**: Activé
   - **Expiration**: 2592000 (30 jours)

### Configuration JSON

```json
{
  "eventsEnabled": true,
  "eventsExpiration": 2592000,
  "eventsListeners": [
    "jboss-logging",
    "custom-webhook-listener"
  ],
  "enabledEventTypes": [
    "REGISTER",
    "LOGIN",
    "UPDATE_PROFILE",
    "UPDATE_EMAIL"
  ],
  "adminEventsEnabled": true,
  "adminEventsDetailsEnabled": true
}
```

## 2. Installation du Plugin Webhook

Keycloak ne supporte pas nativement les webhooks. Nous devons installer un plugin personnalisé.

### Option 1: Plugin Java Custom

Créer un provider Keycloak qui envoie des webhooks:

```java
// KeycloakWebhookEventListenerProvider.java
package com.africare.keycloak;

import org.keycloak.events.Event;
import org.keycloak.events.EventListenerProvider;
import org.keycloak.events.EventType;
import org.keycloak.events.admin.AdminEvent;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

public class KeycloakWebhookEventListenerProvider implements EventListenerProvider {

    private static final String WEBHOOK_URL = System.getenv("WEBHOOK_URL");
    private static final String WEBHOOK_SECRET = System.getenv("WEBHOOK_SECRET");

    private final HttpClient httpClient = HttpClient.newHttpClient();

    @Override
    public void onEvent(Event event) {
        // Filter events we care about
        if (shouldProcessEvent(event.getType())) {
            sendWebhook(event);
        }
    }

    private boolean shouldProcessEvent(EventType type) {
        return type == EventType.REGISTER ||
               type == EventType.LOGIN ||
               type == EventType.UPDATE_PROFILE ||
               type == EventType.UPDATE_EMAIL;
    }

    private void sendWebhook(Event event) {
        try {
            // Build payload
            String payload = buildPayload(event);

            // Calculate signature
            String timestamp = String.valueOf(System.currentTimeMillis() / 1000);
            String signature = calculateSignature(payload, timestamp);

            // Send HTTP request
            HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(WEBHOOK_URL))
                .header("Content-Type", "application/json")
                .header("X-Keycloak-Signature", signature)
                .header("X-Keycloak-Timestamp", timestamp)
                .POST(HttpRequest.BodyPublishers.ofString(payload))
                .build();

            httpClient.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                .thenAccept(response -> {
                    if (response.statusCode() != 200) {
                        // Log error
                        System.err.println("Webhook failed: " + response.statusCode());
                    }
                });

        } catch (Exception e) {
            // Log exception
            e.printStackTrace();
        }
    }

    private String buildPayload(Event event) {
        // Convert event to JSON matching KeycloakWebhookEvent schema
        return String.format(
            "{\"type\":\"%s\",\"realmId\":\"%s\",\"userId\":\"%s\",\"time\":%d,\"details\":%s}",
            event.getType().name(),
            event.getRealmId(),
            event.getUserId(),
            event.getTime(),
            buildDetails(event)
        );
    }

    private String buildDetails(Event event) {
        // Extract user details from event
        Map<String, String> details = event.getDetails();
        // Convert to JSON
        return new Gson().toJson(details);
    }

    private String calculateSignature(String payload, String timestamp) throws Exception {
        String signedPayload = timestamp + "." + payload;

        Mac mac = Mac.getInstance("HmacSHA256");
        SecretKeySpec secretKey = new SecretKeySpec(
            WEBHOOK_SECRET.getBytes(StandardCharsets.UTF_8),
            "HmacSHA256"
        );
        mac.init(secretKey);

        byte[] hash = mac.doFinal(signedPayload.getBytes(StandardCharsets.UTF_8));
        return bytesToHex(hash);
    }

    private String bytesToHex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte b : bytes) {
            result.append(String.format("%02x", b));
        }
        return result.toString();
    }

    @Override
    public void onEvent(AdminEvent adminEvent, boolean includeRepresentation) {
        // Optional: handle admin events
    }

    @Override
    public void close() {
        // Cleanup
    }
}
```

### Déploiement du Plugin

1. **Compiler le plugin:**
   ```bash
   mvn clean package
   ```

2. **Copier le JAR dans Keycloak:**
   ```bash
   cp target/keycloak-webhook-plugin.jar /opt/keycloak/providers/
   ```

3. **Redémarrer Keycloak:**
   ```bash
   systemctl restart keycloak
   ```

4. **Configurer les variables d'environnement:**
   ```bash
   export WEBHOOK_URL="https://identity.africare.sn/api/v1/webhooks/keycloak"
   export WEBHOOK_SECRET="your-webhook-secret-here"
   ```

### Option 2: Utiliser un Service Externe (Zapier/n8n)

Si le plugin custom n'est pas souhaité, utiliser un service d'automation comme **n8n** ou **Zapier**:

1. Configurer Keycloak pour envoyer les événements à un webhook n8n
2. Dans n8n, créer un workflow qui:
   - Reçoit l'événement Keycloak
   - Calcule la signature HMAC-SHA256
   - Formate le payload selon `KeycloakWebhookEvent`
   - Envoie vers `core-africare-identity`

## 3. Configuration des Attributs Personnalisés

Pour que la synchronisation fonctionne, les utilisateurs Keycloak doivent avoir certains attributs:

### Attributs Requis (Patient)

```json
{
  "attributes": {
    "first_name": ["Amadou"],
    "last_name": ["Diallo"],
    "date_of_birth": ["1990-05-15"],
    "gender": ["male"],
    "phone": ["+221771234567"],
    "country": ["Sénégal"],
    "preferred_language": ["fr"]
  }
}
```

### Configuration dans Keycloak

1. Aller dans **Realm Settings** > **User Profile**
2. Ajouter les attributs personnalisés:
   - `date_of_birth` (Required, Validator: date format)
   - `gender` (Required, Validator: options [male, female])
   - `phone` (Optional, Validator: phone number E.164)
   - `national_id` (Optional)
   - `country` (Optional, Default: "Sénégal")
   - `preferred_language` (Optional, Default: "fr")

## 4. Tester la Configuration

### Test Manuel

```bash
# Générer une signature de test
SECRET="your-webhook-secret"
TIMESTAMP=$(date +%s)
PAYLOAD='{"type":"REGISTER","realmId":"africare","userId":"test-user-123","time":1234567890000,"details":{"first_name":"Test","last_name":"User","email":"test@example.com"}}'

# Calculer la signature
SIGNATURE=$(echo -n "${TIMESTAMP}.${PAYLOAD}" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')

# Envoyer le webhook de test
curl -X POST https://identity.africare.sn/api/v1/webhooks/keycloak \
  -H "Content-Type: application/json" \
  -H "X-Keycloak-Signature: $SIGNATURE" \
  -H "X-Keycloak-Timestamp: $TIMESTAMP" \
  -d "$PAYLOAD"
```

### Vérifier les Logs

```bash
# Logs du service identity
docker logs -f core-africare-identity

# Logs Keycloak
tail -f /var/log/keycloak/keycloak.log
```

### Health Check

```bash
# Vérifier l'état du webhook endpoint
curl https://identity.africare.sn/api/v1/webhooks/keycloak/health
```

## 5. Monitoring et Troubleshooting

### Métriques à Surveiller

- **Total événements traités**: Compteur d'événements webhook reçus
- **Taux d'échec**: Pourcentage d'événements en échec
- **Latence**: Temps de traitement par événement
- **Erreurs signature**: Signatures invalides (problème de config)

### Problèmes Courants

#### 1. Signature Invalide (401)

**Cause**: Secret webhook incorrect ou timestamp expiré

**Solution**:
```bash
# Vérifier que le secret est le même partout
echo $WEBHOOK_SECRET  # Keycloak plugin
kubectl get secret webhook-secret -o yaml  # Service identity
```

#### 2. Timeout (504)

**Cause**: Service identity non accessible depuis Keycloak

**Solution**:
```bash
# Tester la connectivité réseau depuis Keycloak
curl -v https://identity.africare.sn/api/v1/webhooks/keycloak/health
```

#### 3. Patient Déjà Existant

**Cause**: Événement REGISTER reçu deux fois

**Solution**: C'est normal, le service détecte et ignore les doublons

#### 4. Champs Manquants (400)

**Cause**: Attributs requis absents dans Keycloak

**Solution**: Configurer le User Profile Keycloak avec validation

## 6. Sécurité

### Best Practices

1. **Secret Rotation**: Changer le webhook secret tous les 90 jours
2. **HTTPS Only**: Toujours utiliser HTTPS pour les webhooks
3. **Firewall**: Restreindre l'accès au endpoint webhook à l'IP de Keycloak
4. **Rate Limiting**: Configurer un rate limit (ex: 100 req/min)
5. **Monitoring**: Alertes sur échecs répétés ou signatures invalides

### Génération du Secret

```bash
# Générer un secret fort
openssl rand -hex 32
```

### Configuration Firewall

```bash
# Autoriser uniquement Keycloak
iptables -A INPUT -p tcp --dport 443 -s <KEYCLOAK_IP> -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j DROP
```

## 7. Rollback et Désactivation

### Désactiver les Webhooks

1. Dans Keycloak Admin UI:
   - **Realm Settings** > **Events**
   - Désactiver `custom-webhook-listener`

2. Ou via CLI:
   ```bash
   kcadm.sh update events/config -r africare \
     -s 'eventsListeners=["jboss-logging"]'
   ```

### Fallback: Synchronisation Manuelle

Si les webhooks échouent, utiliser l'API REST pour sync manuelle:

```bash
# Créer un patient manuellement
curl -X POST https://identity.africare.sn/api/v1/patients \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "keycloak_user_id": "user-uuid",
    "first_name": "Amadou",
    "last_name": "Diallo",
    ...
  }'
```

## Références

- [Keycloak Event Listener SPI](https://www.keycloak.org/docs/latest/server_development/#_events)
- [RFC 9457 - Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html)
- [HMAC-SHA256 Spec](https://tools.ietf.org/html/rfc2104)
