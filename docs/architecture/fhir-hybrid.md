# Architecture FHIR Hybride

Architecture hybride où **HAPI FHIR** stocke les données démographiques et **PostgreSQL** les métadonnées GDPR.

## Composants

### Client FHIR (`app/infrastructure/fhir/client.py`)

Client HTTP async (httpx) avec retry automatique et tracing OpenTelemetry.

```python
fhir_client = app.state.fhir_client

patient = await fhir_client.create(fhir_patient)
patient = await fhir_client.read("Patient", patient_id)
patient = await fhir_client.update(updated_patient)
results = await fhir_client.search("Patient", {"identifier": keycloak_id})
```

### Mappers (`app/infrastructure/fhir/mappers/`)

Conversion bidirectionnelle Pydantic <-> FHIR R4.

**Patient Mapper**: `PatientCreate/Response` <-> `FHIR Patient`
**Professional Mapper**: `ProfessionalCreate/Response` <-> `FHIR Practitioner`

### Modèles GDPR (`app/models/gdpr_metadata.py`)

Tables PostgreSQL légères pour les champs non-FHIR :

- `id` : ID numérique (rétro-compatibilité API)
- `fhir_resource_id` : UUID de la ressource FHIR
- `is_verified`, `notes` : Champs métier
- `under_investigation` : Blocage suppression
- `soft_deleted_at`, `anonymized_at` : GDPR
- `correlation_hash` : Traçabilité post-anonymisation

## Pattern d'Orchestration

```python
async def create_patient(db, fhir_client, patient_data, current_user_id):
    # 1. Mapper vers FHIR
    fhir_patient = PatientMapper.to_fhir(patient_data)

    # 2. Créer dans HAPI FHIR
    created_fhir = await fhir_client.create(fhir_patient)

    # 3. Créer métadonnées GDPR locales
    gdpr = PatientGdprMetadata(fhir_resource_id=created_fhir.id, ...)
    db.add(gdpr)
    await db.commit()

    # 4. Retourner avec ID numérique local
    return PatientMapper.from_fhir(created_fhir, local_id=gdpr.id, ...)
```

## Configuration

```bash
HAPI_FHIR_BASE_URL=http://localhost:8080/fhir
HAPI_FHIR_TIMEOUT=30
```

## Rétro-compatibilité

- Mêmes schémas Pydantic
- Mêmes IDs numériques dans les réponses
- Mêmes endpoints API

## Tests

Mocker le client FHIR :

```python
@pytest.fixture
def mock_fhir_client():
    client = AsyncMock(spec=FHIRClient)
    client.create.return_value = FHIRPatient(id="fhir-uuid-123", ...)
    return client
```
