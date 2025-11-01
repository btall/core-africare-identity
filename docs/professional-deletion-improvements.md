# Amélioration Gestion Suppression Professionnels

## Statut : 🚧 En cours de développement (Phase 1/3 complétée)

Cette feature améliore la gestion de suppression des professionnels de santé avec :
- Période de grâce de 7 jours avant anonymisation définitive
- Blocage des suppressions pendant enquêtes médico-légales
- Système de corrélation pour détecter retours après anonymisation
- Raisons de suppression enrichies

---

## ✅ Phase 1 : Fondations (COMPLÉTÉ)

### Commit 1 : Modèle de données

**Nouveaux champs `Professional`** :

```python
# Enquête médico-légale (bloque suppression)
under_investigation: bool = False
investigation_notes: str | None

# Corrélation pour détecter retours
correlation_hash: str | None  # SHA-256(email+professional_id+salt)

# Soft delete avec période de grâce
soft_deleted_at: datetime | None  # Début période grâce 7j
anonymized_at: datetime | None     # Anonymisation définitive

# Raisons de suppression enrichies
deletion_reason: Literal[
    "user_request",
    "admin_termination",
    "professional_revocation",
    "gdpr_compliance",
    "prolonged_inactivity",
]
```

**Migration Alembic** : `23f6c23e1f1b`
- 5 nouvelles colonnes avec indices
- Server default pour `under_investigation=false`
- Rétro-compatible avec données existantes

### Commit 2 : Schémas et Exceptions

**Nouvelle exception RFC 9457** :
- `ProfessionalDeletionBlockedError` (HTTP 423 Locked)
- Levée quand `under_investigation=True`

**Nouveaux schémas Pydantic** :
- `DeletionReason` (Literal type)
- `ProfessionalDeletionRequest`
- `ProfessionalRestoreRequest`
- `ProfessionalInvestigationUpdate`

### Commit 3 : Système de Corrélation

**Fonctions implémentées** :
```python
def _generate_correlation_hash(email, professional_id) -> str:
    """Hash SHA-256 déterministe pour corrélation anonymisée."""

async def _check_returning_professional(db, email, professional_id) -> Professional | None:
    """Détecte si professionnel anonymisé revient."""
```

**Tests unitaires** : `tests/unit/test_correlation_hash.py` (6 tests)

---

## 🚧 Phase 2 : Logique Métier (À FAIRE)

### Commit 4-5 : Soft Delete avec Période de Grâce

**Modifications `sync_user_deletion()`** :
1. Vérifier `under_investigation` (bloquer si True)
2. Générer `correlation_hash` AVANT anonymisation
3. Soft delete : `is_active=False`, `soft_deleted_at=now()`
4. Publier événement `identity.professional.soft_deleted` avec :
   - `anonymization_scheduled_at` (now + 7 jours)
   - `grace_period_days: 7`

**Événement Rendez-vous** :
```python
await publish("identity.professional.appointments_action_required", {
    "professional_id": ...,
    "action": "pending_reassignment",
    "grace_period_end": ...,
    "instructions": {
        "days_0_to_7": "maintain_appointments",
        "day_7": "propose_reassignment",
        "fallback": "cancel_with_notification"
    }
})
```

### Commit 6 : Anonymisation Différée

**Fonction `anonymize_expired_deletions()`** :
- Tâche schedulée quotidienne (APScheduler/Celery)
- Trouve professionnels `soft_deleted_at < now() - 7 days`
- Appelle `_anonymize()` pour chacun
- Définit `anonymized_at = now()`
- Publie `identity.professional.anonymized`

### Commit 7 : Détection Retours

**Modifications `sync_user_registration()`** :
```python
returning = await _check_returning_professional(db, event.email, event.professional_id)
if returning:
    await publish("identity.professional.returning_detected", {
        "new_keycloak_user_id": event.user_id,
        "previous_professional_id": returning.id,
        "anonymized_at": returning.anonymized_at,
        "correlation_hash": returning.correlation_hash
    })
    # Créer NOUVEAU profil (anonymisation irréversible)
```

---

## 🔜 Phase 3 : API et Documentation (À FAIRE)

### Commit 8 : Endpoints Administrateur

**POST `/api/v1/professionals/{id}/investigate`** :
- Définir `under_investigation=True`
- Bloquer toute suppression
- Admin uniquement

**POST `/api/v1/professionals/{id}/restore`** :
- Restaurer durant période de grâce (< 7 jours)
- Définir `is_active=True`, `soft_deleted_at=None`
- Publier `identity.professional.restored`

**DELETE `/api/v1/professionals/{id}`** (modifié) :
- Utiliser nouveau workflow soft delete
- Accepter `ProfessionalDeletionRequest`

### Commit 9-10 : Documentation

- Diagrammes de séquence (workflow complet)
- Guide API avec exemples
- Mise à jour CLAUDE.md

---

## Configuration Requise

### Variables d'Environnement

```bash
# Salt pour génération correlation_hash (optionnel, défaut fourni)
CORRELATION_HASH_SALT=africare-identity-salt-v1

# Scheduler pour anonymisation différée (Phase 2)
# APScheduler (léger) OU Celery (si déjà utilisé dans plateforme)
```

### Dépendances Futures (Phase 2)

```toml
# pyproject.toml
apscheduler = "^3.10.4"  # Pour anonymisation schedulée J+7
```

---

## Tests

### Tests Existants
- ✅ `test_correlation_hash.py` : 6 tests (3 unitaires, 3 intégration)

### Tests À Créer (Phase 2)
- `test_soft_delete_workflow.py`
- `test_anonymize_expired_deletions.py`
- `test_deletion_blocked_under_investigation.py`
- `test_returning_professional_detection.py`

---

## Workflow Complet (Quand Phase 2-3 terminées)

### Suppression Normale

1. **J+0** : Événement DELETE reçu
   - Vérifier `under_investigation` → bloquer si True
   - Générer `correlation_hash`
   - Soft delete : `is_active=False`, `soft_deleted_at=now()`
   - Publier événement avec `grace_period_end`

2. **J+0 à J+7** : Période de grâce
   - Professionnel désactivé mais données préservées
   - Restauration possible via API
   - Rendez-vous maintenus en attente

3. **J+7** : Anonymisation automatique
   - Tâche schedulée détecte expiration
   - Appelle `_anonymize()` : Hash bcrypt irréversible
   - Définit `anonymized_at`
   - Publier `identity.professional.anonymized`
   - Rendez-vous réaffectés ou annulés

### Détection Retour

1. Nouveau professionnel s'inscrit
2. `_check_returning_professional()` vérifie `correlation_hash`
3. Si match trouvé : Publier événement `returning_detected`
4. Créer nouveau profil (ancien irréversible)

### Enquête En Cours

1. Admin définit `under_investigation=True`
2. Toute tentative de suppression → HTTP 423 Locked
3. Enquête terminée → Admin définit `under_investigation=False`
4. Suppression possible à nouveau

---

## Roadmap

- [x] **Phase 1** : Fondations (modèle, schémas, corrélation) - *COMPLÉTÉ*
- [ ] **Phase 2** : Logique métier (soft delete, scheduler, événements)
- [ ] **Phase 3** : API et documentation

**Estimation restante** : 4-5 jours développement

---

## Liens Utiles

- Migration Alembic : `alembic/versions/23f6c23e1f1b_*.py`
- Tests : `tests/unit/test_correlation_hash.py`
- Schémas : `app/schemas/professional.py` (lignes 229-279)
- Exception : `app/core/exceptions.py` (ligne 109)
