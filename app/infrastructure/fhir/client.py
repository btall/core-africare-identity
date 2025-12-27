"""Async FHIR client for HAPI FHIR server communication.

This module provides an async HTTP client for interacting with HAPI FHIR servers,
with built-in retry logic, OpenTelemetry tracing, and proper error handling.
"""

import json
from typing import TypeVar

import httpx
from fhir.resources.bundle import Bundle
from fhir.resources.patient import Patient as FHIRPatient
from fhir.resources.practitioner import Practitioner as FHIRPractitioner
from opentelemetry import trace
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.infrastructure.fhir.config import fhir_settings
from app.infrastructure.fhir.exceptions import (
    FHIRConnectionError,
    FHIROperationError,
    FHIRResourceNotFoundError,
)

T = TypeVar("T", FHIRPatient, FHIRPractitioner)

tracer = trace.get_tracer(__name__)


class FHIRClient:
    """Async FHIR client with retry and OpenTelemetry tracing.

    This client provides CRUD operations for FHIR resources with:
    - Automatic retry on transient failures
    - OpenTelemetry distributed tracing
    - Proper error handling with custom exceptions

    Example:
        ```python
        client = FHIRClient("http://hapi-fhir:8080/fhir")
        patient = await client.create(fhir_patient)
        await client.close()
        ```
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
    ):
        """Initialize the FHIR client.

        Args:
            base_url: FHIR server base URL. Defaults to settings.
            timeout: Request timeout in seconds. Defaults to settings.
        """
        self.base_url = (base_url or str(fhir_settings.HAPI_FHIR_BASE_URL)).rstrip("/")
        self.timeout = timeout or fhir_settings.HAPI_FHIR_TIMEOUT
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Content-Type": "application/fhir+json",
                    "Accept": "application/fhir+json",
                },
            )
        return self._client

    @retry(
        stop=stop_after_attempt(fhir_settings.HAPI_FHIR_RETRY_ATTEMPTS),
        wait=wait_exponential(
            multiplier=fhir_settings.HAPI_FHIR_RETRY_DELAY,
            min=1,
            max=10,
        ),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def create(self, resource: T) -> T:
        """Create a FHIR resource on the server.

        Args:
            resource: FHIR resource to create (Patient or Practitioner)

        Returns:
            Created resource with server-assigned ID

        Raises:
            FHIRConnectionError: If connection to server fails
            FHIROperationError: If server returns an error
        """
        resource_type = resource.get_resource_type()
        with tracer.start_as_current_span(f"fhir_create_{resource_type}") as span:
            span.set_attribute("fhir.resource_type", resource_type)

            try:
                client = await self._get_client()
                response = await client.post(
                    f"/{resource_type}",
                    content=resource.model_dump_json(exclude_none=True),
                )

                if response.status_code in (200, 201):
                    created = type(resource).model_validate_json(response.content)
                    span.set_attribute("fhir.resource_id", created.id)
                    span.add_event("Resource created successfully")
                    return created

                # Handle error response
                self._handle_error_response(response, span)

            except httpx.ConnectError as e:
                span.record_exception(e)
                raise FHIRConnectionError(f"Failed to connect to FHIR server: {e}")
            except httpx.TimeoutException as e:
                span.record_exception(e)
                raise FHIRConnectionError(f"FHIR server request timed out: {e}")

    @retry(
        stop=stop_after_attempt(fhir_settings.HAPI_FHIR_RETRY_ATTEMPTS),
        wait=wait_exponential(
            multiplier=fhir_settings.HAPI_FHIR_RETRY_DELAY,
            min=1,
            max=10,
        ),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def read(
        self, resource_type: str, resource_id: str
    ) -> FHIRPatient | FHIRPractitioner | None:
        """Read a FHIR resource by ID.

        Args:
            resource_type: Type of resource ("Patient" or "Practitioner")
            resource_id: Server-assigned resource ID

        Returns:
            FHIR resource if found, None if not found

        Raises:
            FHIRConnectionError: If connection to server fails
            FHIROperationError: If server returns an error (other than 404)
        """
        with tracer.start_as_current_span(f"fhir_read_{resource_type}") as span:
            span.set_attribute("fhir.resource_type", resource_type)
            span.set_attribute("fhir.resource_id", resource_id)

            try:
                client = await self._get_client()
                response = await client.get(f"/{resource_type}/{resource_id}")

                if response.status_code == 404:
                    span.add_event("Resource not found")
                    return None

                if response.status_code == 200:
                    span.add_event("Resource found")
                    if resource_type == "Patient":
                        return FHIRPatient.model_validate_json(response.content)
                    elif resource_type == "Practitioner":
                        return FHIRPractitioner.model_validate_json(response.content)

                self._handle_error_response(response, span)

            except httpx.ConnectError as e:
                span.record_exception(e)
                raise FHIRConnectionError(f"Failed to connect to FHIR server: {e}")
            except httpx.TimeoutException as e:
                span.record_exception(e)
                raise FHIRConnectionError(f"FHIR server request timed out: {e}")

    @retry(
        stop=stop_after_attempt(fhir_settings.HAPI_FHIR_RETRY_ATTEMPTS),
        wait=wait_exponential(
            multiplier=fhir_settings.HAPI_FHIR_RETRY_DELAY,
            min=1,
            max=10,
        ),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def update(self, resource: T) -> T:
        """Update an existing FHIR resource.

        Args:
            resource: FHIR resource with ID set

        Returns:
            Updated resource

        Raises:
            FHIRResourceNotFoundError: If resource doesn't exist
            FHIRConnectionError: If connection to server fails
            FHIROperationError: If server returns an error
        """
        resource_type = resource.get_resource_type()
        resource_id = resource.id

        with tracer.start_as_current_span(f"fhir_update_{resource_type}") as span:
            span.set_attribute("fhir.resource_type", resource_type)
            span.set_attribute("fhir.resource_id", resource_id)

            try:
                client = await self._get_client()
                response = await client.put(
                    f"/{resource_type}/{resource_id}",
                    content=resource.model_dump_json(exclude_none=True),
                )

                if response.status_code == 404:
                    raise FHIRResourceNotFoundError(resource_type, resource_id)

                if response.status_code in (200, 201):
                    span.add_event("Resource updated successfully")
                    return type(resource).model_validate_json(response.content)

                self._handle_error_response(response, span)

            except httpx.ConnectError as e:
                span.record_exception(e)
                raise FHIRConnectionError(f"Failed to connect to FHIR server: {e}")
            except httpx.TimeoutException as e:
                span.record_exception(e)
                raise FHIRConnectionError(f"FHIR server request timed out: {e}")

    @retry(
        stop=stop_after_attempt(fhir_settings.HAPI_FHIR_RETRY_ATTEMPTS),
        wait=wait_exponential(
            multiplier=fhir_settings.HAPI_FHIR_RETRY_DELAY,
            min=1,
            max=10,
        ),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def search(
        self,
        resource_type: str,
        params: dict[str, str] | None = None,
    ) -> Bundle:
        """Search for FHIR resources.

        Args:
            resource_type: Type of resource to search ("Patient" or "Practitioner")
            params: FHIR search parameters

        Returns:
            Bundle containing matching resources

        Raises:
            FHIRConnectionError: If connection to server fails
            FHIROperationError: If server returns an error
        """
        with tracer.start_as_current_span(f"fhir_search_{resource_type}") as span:
            span.set_attribute("fhir.resource_type", resource_type)
            if params:
                span.set_attribute("fhir.search_params", json.dumps(params))

            try:
                client = await self._get_client()
                response = await client.get(f"/{resource_type}", params=params or {})

                if response.status_code == 200:
                    bundle = Bundle.model_validate_json(response.content)
                    span.set_attribute("fhir.search_total", bundle.total or 0)
                    span.add_event("Search completed")
                    return bundle

                self._handle_error_response(response, span)

            except httpx.ConnectError as e:
                span.record_exception(e)
                raise FHIRConnectionError(f"Failed to connect to FHIR server: {e}")
            except httpx.TimeoutException as e:
                span.record_exception(e)
                raise FHIRConnectionError(f"FHIR server request timed out: {e}")

    async def search_by_identifier(
        self,
        resource_type: str,
        system: str,
        value: str,
    ) -> FHIRPatient | FHIRPractitioner | None:
        """Search for a resource by identifier system and value.

        Args:
            resource_type: Type of resource ("Patient" or "Practitioner")
            system: Identifier system URI
            value: Identifier value

        Returns:
            First matching resource or None if not found
        """
        with tracer.start_as_current_span(f"fhir_search_by_identifier_{resource_type}") as span:
            span.set_attribute("fhir.identifier_system", system)
            span.set_attribute("fhir.identifier_value", value)

            bundle = await self.search(
                resource_type,
                params={"identifier": f"{system}|{value}"},
            )

            if bundle.entry and len(bundle.entry) > 0:
                resource = bundle.entry[0].resource
                span.set_attribute("fhir.resource_id", resource.id)
                return resource

            span.add_event("No matching resource found")
            return None

    def _handle_error_response(self, response: httpx.Response, span: trace.Span) -> None:
        """Handle non-success HTTP responses.

        Args:
            response: HTTP response from FHIR server
            span: Current OpenTelemetry span

        Raises:
            FHIROperationError: Always raised with error details
        """
        try:
            outcome = response.json()
        except json.JSONDecodeError:
            outcome = {"text": response.text}

        error_msg = f"FHIR operation failed with status {response.status_code}"
        span.set_attribute("fhir.error_status", response.status_code)
        span.add_event("FHIR operation failed", {"status_code": response.status_code})

        raise FHIROperationError(
            status_code=response.status_code,
            message=error_msg,
            operation_outcome=outcome,
        )

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client:
            await self._client.aclose()
            self._client = None


# =============================================================================
# Singleton Pattern - Module-level FHIR client
# =============================================================================

_fhir_client: FHIRClient | None = None


def get_fhir_client() -> FHIRClient:
    """Get the singleton FHIR client instance.

    This function provides access to the module-level FHIR client that is
    initialized during application startup (lifespan).

    Returns:
        FHIRClient: The initialized FHIR client

    Raises:
        RuntimeError: If client has not been initialized (app not started)

    Example:
        ```python
        from app.infrastructure.fhir.client import get_fhir_client

        async def my_service_function(db):
            fhir_client = get_fhir_client()
            patient = await fhir_client.read("Patient", "123")
        ```
    """
    if _fhir_client is None:
        raise RuntimeError(
            "FHIR client not initialized. Ensure the application lifespan has started properly."
        )
    return _fhir_client


async def initialize_fhir_client(
    base_url: str | None = None,
    timeout: int | None = None,
) -> FHIRClient:
    """Initialize the singleton FHIR client.

    Called during application startup (lifespan). Creates the module-level
    FHIR client instance that will be used throughout the application.

    Args:
        base_url: FHIR server base URL. Defaults to settings.
        timeout: Request timeout in seconds. Defaults to settings.

    Returns:
        FHIRClient: The initialized client instance
    """
    global _fhir_client
    _fhir_client = FHIRClient(base_url=base_url, timeout=timeout)
    return _fhir_client


async def close_fhir_client() -> None:
    """Close the singleton FHIR client.

    Called during application shutdown (lifespan). Properly closes the
    HTTP client and releases resources.
    """
    global _fhir_client
    if _fhir_client is not None:
        await _fhir_client.close()
        _fhir_client = None
