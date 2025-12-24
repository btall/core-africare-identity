# Configuration Client FHIR

Ce document détaille l'implémentation du client HTTP async pour HAPI FHIR.

## Configuration

**Fichier**: `app/infrastructure/fhir/config.py`

```python
"""Configuration pour le client FHIR."""

from pydantic_settings import BaseSettings


class FHIRSettings(BaseSettings):
    """Configuration HAPI FHIR."""

    HAPI_FHIR_BASE_URL: str = "http://localhost:8090/fhir"
    HAPI_FHIR_TIMEOUT: int = 30
    HAPI_FHIR_AUTH_TOKEN: str | None = None

    model_config = {"env_prefix": "", "case_sensitive": True}


fhir_settings = FHIRSettings()
```

## Systèmes d'Identifiants

**Fichier**: `app/infrastructure/fhir/identifiers.py`

```python
"""Systèmes d'identifiants FHIR pour AfriCare."""

# Authentification Keycloak
KEYCLOAK_SYSTEM = "https://keycloak.africare.app/realms/africare"

# Identité nationale sénégalaise
NATIONAL_ID_SYSTEM = "http://senegal.gov.sn/nin"

# Licences professionnelles
CNOM_SYSTEM = "http://cnom.sn/registry"  # Conseil National de l'Ordre des Médecins
CNOP_SYSTEM = "http://cnop.sn/registry"  # Conseil National de l'Ordre des Pharmaciens

# Assurance maladie
CNAM_SYSTEM = "http://cnam.sn/beneficiary"
```

## Exceptions

**Fichier**: `app/infrastructure/fhir/exceptions.py`

```python
"""Exceptions pour le client FHIR."""


class FHIRError(Exception):
    """Erreur de base pour les opérations FHIR."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class FHIRNotFoundError(FHIRError):
    """Ressource FHIR non trouvée (404)."""

    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            f"{resource_type}/{resource_id} not found",
            status_code=404,
        )


class FHIRValidationError(FHIRError):
    """Erreur de validation FHIR (400/422)."""

    def __init__(self, message: str, issues: list | None = None):
        self.issues = issues or []
        super().__init__(message, status_code=422)


class FHIRConnectionError(FHIRError):
    """Erreur de connexion au serveur FHIR."""

    def __init__(self, message: str):
        super().__init__(message, status_code=503)
```

## Client HTTP Async

**Fichier**: `app/infrastructure/fhir/client.py`

```python
"""Client HTTP async pour HAPI FHIR."""

import logging
from typing import TypeVar

import httpx
from fhir.resources.patient import Patient
from fhir.resources.practitioner import Practitioner
from fhir.resources.resource import Resource

from app.infrastructure.fhir.config import fhir_settings
from app.infrastructure.fhir.exceptions import (
    FHIRConnectionError,
    FHIRError,
    FHIRNotFoundError,
    FHIRValidationError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Resource)


class FHIRClient:
    """Client HTTP async pour HAPI FHIR."""

    def __init__(self):
        self.base_url = fhir_settings.HAPI_FHIR_BASE_URL
        self.timeout = fhir_settings.HAPI_FHIR_TIMEOUT
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Obtient ou crée le client HTTP."""
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/fhir+json"}
            if fhir_settings.HAPI_FHIR_AUTH_TOKEN:
                headers["Authorization"] = f"Bearer {fhir_settings.HAPI_FHIR_AUTH_TOKEN}"

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        """Ferme le client HTTP."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def create(self, resource: T) -> T:
        """Crée une ressource FHIR."""
        resource_type = resource.__class__.__name__
        logger.info(f"Creating FHIR {resource_type}")

        try:
            client = await self._get_client()
            response = await client.post(
                f"/{resource_type}",
                content=resource.json(),
            )
            self._handle_response(response, resource_type, "create")
            return resource.__class__.parse_raw(response.text)

        except httpx.ConnectError as e:
            raise FHIRConnectionError(f"Cannot connect to FHIR server: {e}")

    async def read(self, resource_class: type[T], resource_id: str) -> T | None:
        """Lit une ressource FHIR par ID."""
        resource_type = resource_class.__name__
        logger.info(f"Reading FHIR {resource_type}/{resource_id}")

        try:
            client = await self._get_client()
            response = await client.get(f"/{resource_type}/{resource_id}")

            if response.status_code == 404:
                return None

            self._handle_response(response, resource_type, "read")
            return resource_class.parse_raw(response.text)

        except httpx.ConnectError as e:
            raise FHIRConnectionError(f"Cannot connect to FHIR server: {e}")

    async def update(self, resource: T) -> T:
        """Met à jour une ressource FHIR."""
        resource_type = resource.__class__.__name__
        resource_id = resource.id
        logger.info(f"Updating FHIR {resource_type}/{resource_id}")

        try:
            client = await self._get_client()
            response = await client.put(
                f"/{resource_type}/{resource_id}",
                content=resource.json(),
            )
            self._handle_response(response, resource_type, "update")
            return resource.__class__.parse_raw(response.text)

        except httpx.ConnectError as e:
            raise FHIRConnectionError(f"Cannot connect to FHIR server: {e}")

    async def search(
        self,
        resource_class: type[T],
        params: dict[str, str],
    ) -> list[T]:
        """Recherche des ressources FHIR."""
        resource_type = resource_class.__name__
        logger.info(f"Searching FHIR {resource_type} with {params}")

        try:
            client = await self._get_client()
            response = await client.get(f"/{resource_type}", params=params)
            self._handle_response(response, resource_type, "search")

            bundle = response.json()
            resources = []

            for entry in bundle.get("entry", []):
                if "resource" in entry:
                    resources.append(
                        resource_class.parse_obj(entry["resource"])
                    )

            return resources

        except httpx.ConnectError as e:
            raise FHIRConnectionError(f"Cannot connect to FHIR server: {e}")

    async def search_by_identifier(
        self,
        resource_class: type[T],
        system: str,
        value: str,
    ) -> T | None:
        """Recherche une ressource par identifiant."""
        results = await self.search(
            resource_class,
            {"identifier": f"{system}|{value}"},
        )
        return results[0] if results else None

    def _handle_response(
        self,
        response: httpx.Response,
        resource_type: str,
        operation: str,
    ) -> None:
        """Gère les réponses HTTP et lève les exceptions appropriées."""
        if response.is_success:
            return

        if response.status_code == 404:
            raise FHIRNotFoundError(resource_type, "unknown")

        if response.status_code in (400, 422):
            try:
                outcome = response.json()
                issues = outcome.get("issue", [])
                message = "; ".join(
                    i.get("diagnostics", "Unknown error") for i in issues
                )
            except Exception:
                message = response.text

            raise FHIRValidationError(message)

        raise FHIRError(
            f"FHIR {operation} failed: {response.status_code} - {response.text}",
            status_code=response.status_code,
        )


# Singleton instance
fhir_client = FHIRClient()
```

## Utilisation

```python
from fhir.resources.patient import Patient
from app.infrastructure.fhir.client import fhir_client

# Créer un patient
patient = Patient(
    name=[{"family": "Diallo", "given": ["Amadou"]}],
    active=True,
)
created = await fhir_client.create(patient)
print(f"Created patient: {created.id}")

# Lire un patient
patient = await fhir_client.read(Patient, created.id)

# Rechercher par identifiant
patient = await fhir_client.search_by_identifier(
    Patient,
    "https://keycloak.africare.app/realms/africare",
    "user-uuid-123",
)
```
