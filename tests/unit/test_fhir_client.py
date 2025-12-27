"""Tests unitaires pour le client FHIR.

Ce module teste le client FHIR async avec mock des appels HTTP.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fhir.resources.bundle import Bundle
from fhir.resources.patient import Patient as FHIRPatient
from fhir.resources.practitioner import Practitioner as FHIRPractitioner

from app.infrastructure.fhir.client import (
    FHIRClient,
    close_fhir_client,
    get_fhir_client,
    initialize_fhir_client,
)
from app.infrastructure.fhir.exceptions import (
    FHIRConnectionError,
    FHIROperationError,
    FHIRResourceNotFoundError,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fhir_client():
    """Create a test FHIR client."""
    return FHIRClient(base_url="http://test-fhir:8080/fhir", timeout=10)


@pytest.fixture
def mock_patient():
    """Create a mock FHIR Patient."""
    return FHIRPatient(
        id="patient-123",
        active=True,
        name=[{"family": "Diallo", "given": ["Amadou"]}],
    )


@pytest.fixture
def mock_practitioner():
    """Create a mock FHIR Practitioner."""
    return FHIRPractitioner(
        id="practitioner-456",
        active=True,
        name=[{"family": "Ndiaye", "given": ["Fatou"]}],
    )


@pytest.fixture
def mock_bundle():
    """Create a mock FHIR Bundle."""
    return Bundle(
        type="searchset",
        total=2,
        entry=[
            {"resource": {"resourceType": "Patient", "id": "p1", "active": True}},
            {"resource": {"resourceType": "Patient", "id": "p2", "active": True}},
        ],
    )


# =============================================================================
# Tests FHIRClient initialization
# =============================================================================


class TestFHIRClientInit:
    """Tests pour l'initialisation du FHIRClient."""

    def test_init_with_defaults(self):
        """Test initialization avec valeurs par defaut."""
        client = FHIRClient()

        assert client.base_url is not None
        assert client.timeout is not None
        assert client._client is None

    def test_init_with_custom_values(self):
        """Test initialization avec valeurs personnalisees."""
        client = FHIRClient(
            base_url="http://custom-fhir:8080/fhir/",
            timeout=60,
        )

        assert client.base_url == "http://custom-fhir:8080/fhir"  # Trailing slash removed
        assert client.timeout == 60

    def test_base_url_trailing_slash_removed(self):
        """Test que le trailing slash est retire du base_url."""
        client = FHIRClient(base_url="http://fhir/test/")

        assert client.base_url == "http://fhir/test"


# =============================================================================
# Tests FHIRClient._get_client()
# =============================================================================


class TestFHIRClientGetClient:
    """Tests pour _get_client()."""

    @pytest.mark.asyncio
    async def test_get_client_creates_new_client(self, fhir_client):
        """Test que _get_client cree un nouveau client."""
        client = await fhir_client._get_client()

        assert client is not None
        assert isinstance(client, httpx.AsyncClient)
        assert fhir_client._client is client

        # Cleanup
        await fhir_client.close()

    @pytest.mark.asyncio
    async def test_get_client_reuses_existing_client(self, fhir_client):
        """Test que _get_client reutilise le client existant."""
        client1 = await fhir_client._get_client()
        client2 = await fhir_client._get_client()

        assert client1 is client2

        # Cleanup
        await fhir_client.close()


# =============================================================================
# Tests FHIRClient.create()
# =============================================================================


class TestFHIRClientCreate:
    """Tests pour create()."""

    @pytest.mark.asyncio
    async def test_create_patient_success(self, fhir_client, mock_patient):
        """Test creation reussie d'un Patient."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.content = mock_patient.model_dump_json().encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.create(mock_patient)

            assert result.id == "patient-123"
            mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_practitioner_success(self, fhir_client, mock_practitioner):
        """Test creation reussie d'un Practitioner."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_practitioner.model_dump_json().encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.create(mock_practitioner)

            assert result.id == "practitioner-456"

    @pytest.mark.asyncio
    async def test_create_connection_error(self, fhir_client, mock_patient):
        """Test erreur de connexion lors de la creation."""
        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_get.return_value = mock_http_client

            with pytest.raises(FHIRConnectionError) as exc_info:
                await fhir_client.create(mock_patient)

            assert "Failed to connect" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_timeout_error(self, fhir_client, mock_patient):
        """Test timeout lors de la creation."""
        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_get.return_value = mock_http_client

            with pytest.raises(FHIRConnectionError) as exc_info:
                await fhir_client.create(mock_patient)

            assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_server_error(self, fhir_client, mock_patient):
        """Test erreur serveur lors de la creation."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Internal Server Error"}
        mock_response.text = "Internal Server Error"

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            with pytest.raises(FHIROperationError) as exc_info:
                await fhir_client.create(mock_patient)

            assert exc_info.value.status_code == 500


# =============================================================================
# Tests FHIRClient.read()
# =============================================================================


class TestFHIRClientRead:
    """Tests pour read()."""

    @pytest.mark.asyncio
    async def test_read_patient_found(self, fhir_client, mock_patient):
        """Test lecture Patient trouve."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_patient.model_dump_json().encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.read("Patient", "patient-123")

            assert isinstance(result, FHIRPatient)
            assert result.id == "patient-123"

    @pytest.mark.asyncio
    async def test_read_practitioner_found(self, fhir_client, mock_practitioner):
        """Test lecture Practitioner trouve."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_practitioner.model_dump_json().encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.read("Practitioner", "practitioner-456")

            assert isinstance(result, FHIRPractitioner)
            assert result.id == "practitioner-456"

    @pytest.mark.asyncio
    async def test_read_not_found(self, fhir_client):
        """Test lecture ressource non trouvee (404)."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.read("Patient", "nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_read_connection_error(self, fhir_client):
        """Test erreur de connexion lors de la lecture."""
        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_get.return_value = mock_http_client

            with pytest.raises(FHIRConnectionError):
                await fhir_client.read("Patient", "123")


# =============================================================================
# Tests FHIRClient.update()
# =============================================================================


class TestFHIRClientUpdate:
    """Tests pour update()."""

    @pytest.mark.asyncio
    async def test_update_success(self, fhir_client, mock_patient):
        """Test mise a jour reussie."""
        mock_patient.active = False  # Modify
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_patient.model_dump_json().encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.put = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.update(mock_patient)

            assert result.id == "patient-123"
            assert result.active is False

    @pytest.mark.asyncio
    async def test_update_not_found(self, fhir_client, mock_patient):
        """Test mise a jour ressource non trouvee."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.put = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            with pytest.raises(FHIRResourceNotFoundError) as exc_info:
                await fhir_client.update(mock_patient)

            assert exc_info.value.resource_type == "Patient"
            assert exc_info.value.resource_id == "patient-123"

    @pytest.mark.asyncio
    async def test_update_connection_error(self, fhir_client, mock_patient):
        """Test erreur de connexion lors de la mise a jour."""
        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.put = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_get.return_value = mock_http_client

            with pytest.raises(FHIRConnectionError):
                await fhir_client.update(mock_patient)


# =============================================================================
# Tests FHIRClient.search()
# =============================================================================


class TestFHIRClientSearch:
    """Tests pour search()."""

    @pytest.mark.asyncio
    async def test_search_success(self, fhir_client, mock_bundle):
        """Test recherche reussie."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_bundle.model_dump_json().encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.search("Patient", {"active": "true"})

            assert isinstance(result, Bundle)
            assert result.total == 2
            mock_http_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_no_params(self, fhir_client, mock_bundle):
        """Test recherche sans parametres."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = mock_bundle.model_dump_json().encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.search("Patient")

            assert isinstance(result, Bundle)

    @pytest.mark.asyncio
    async def test_search_server_error(self, fhir_client):
        """Test erreur serveur lors de la recherche."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "Server Error"}
        mock_response.text = "Internal Server Error"

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            with pytest.raises(FHIROperationError):
                await fhir_client.search("Patient")


# =============================================================================
# Tests FHIRClient.search_by_identifier()
# =============================================================================


class TestFHIRClientSearchByIdentifier:
    """Tests pour search_by_identifier()."""

    @pytest.mark.asyncio
    async def test_search_by_identifier_found(self, fhir_client, mock_patient):
        """Test recherche par identifiant trouvee."""
        bundle = Bundle(
            type="searchset",
            total=1,
            entry=[{"resource": mock_patient.model_dump()}],
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = bundle.model_dump_json().encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.search_by_identifier(
                "Patient",
                "http://keycloak.example/",
                "user-123",
            )

            assert result is not None
            assert result.id == "patient-123"

    @pytest.mark.asyncio
    async def test_search_by_identifier_not_found(self, fhir_client):
        """Test recherche par identifiant non trouvee."""
        empty_bundle = Bundle(type="searchset", total=0)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = empty_bundle.model_dump_json().encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            result = await fhir_client.search_by_identifier(
                "Patient",
                "http://keycloak.example/",
                "nonexistent",
            )

            assert result is None


# =============================================================================
# Tests FHIRClient._handle_error_response()
# =============================================================================


class TestFHIRClientHandleErrorResponse:
    """Tests pour _handle_error_response()."""

    def test_handle_error_with_json_body(self, fhir_client):
        """Test gestion erreur avec corps JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": "invalid"}],
        }

        mock_span = MagicMock()

        with pytest.raises(FHIROperationError) as exc_info:
            fhir_client._handle_error_response(mock_response, mock_span)

        assert exc_info.value.status_code == 400
        assert exc_info.value.operation_outcome is not None

    def test_handle_error_with_non_json_body(self, fhir_client):
        """Test gestion erreur avec corps non-JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.json.side_effect = json.JSONDecodeError("", "", 0)
        mock_response.text = "Bad Gateway"

        mock_span = MagicMock()

        with pytest.raises(FHIROperationError) as exc_info:
            fhir_client._handle_error_response(mock_response, mock_span)

        assert exc_info.value.status_code == 502
        assert exc_info.value.operation_outcome == {"text": "Bad Gateway"}


# =============================================================================
# Tests FHIRClient.close()
# =============================================================================


class TestFHIRClientClose:
    """Tests pour close()."""

    @pytest.mark.asyncio
    async def test_close_with_client(self, fhir_client):
        """Test fermeture avec client initialise."""
        # Initialize the client
        await fhir_client._get_client()
        assert fhir_client._client is not None

        # Close it
        await fhir_client.close()

        assert fhir_client._client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self, fhir_client):
        """Test fermeture sans client initialise."""
        assert fhir_client._client is None

        # Should not raise
        await fhir_client.close()

        assert fhir_client._client is None


# =============================================================================
# Tests Singleton Functions
# =============================================================================


class TestSingletonFunctions:
    """Tests pour les fonctions singleton."""

    @pytest.mark.asyncio
    async def test_get_fhir_client_not_initialized(self):
        """Test get_fhir_client avant initialisation."""
        # Ensure client is not initialized
        await close_fhir_client()

        with pytest.raises(RuntimeError) as exc_info:
            get_fhir_client()

        assert "FHIR client not initialized" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_initialize_and_get_fhir_client(self):
        """Test cycle complet initialize -> get -> close."""
        # Initialize
        client = await initialize_fhir_client(
            base_url="http://test:8080/fhir",
            timeout=15,
        )

        assert client is not None
        assert isinstance(client, FHIRClient)

        # Get should return the same instance
        retrieved = get_fhir_client()
        assert retrieved is client

        # Cleanup
        await close_fhir_client()

        # After close, get should fail
        with pytest.raises(RuntimeError):
            get_fhir_client()

    @pytest.mark.asyncio
    async def test_close_fhir_client_idempotent(self):
        """Test que close_fhir_client est idempotent."""
        # Initialize
        await initialize_fhir_client()

        # Close multiple times should not raise
        await close_fhir_client()
        await close_fhir_client()
        await close_fhir_client()


# =============================================================================
# Tests pour les exceptions FHIR
# =============================================================================


class TestFHIRExceptions:
    """Tests pour les exceptions FHIR."""

    def test_fhir_connection_error(self):
        """Test FHIRConnectionError."""
        error = FHIRConnectionError("Connection refused")

        assert str(error) == "Connection refused"
        assert error.message == "Connection refused"
        assert error.details == {}

    def test_fhir_resource_not_found_error(self):
        """Test FHIRResourceNotFoundError."""
        error = FHIRResourceNotFoundError("Patient", "123")

        assert "Patient/123 not found" in str(error)
        assert error.resource_type == "Patient"
        assert error.resource_id == "123"
        assert error.details["resource_type"] == "Patient"

    def test_fhir_operation_error(self):
        """Test FHIROperationError."""
        outcome = {"issue": [{"severity": "error"}]}
        error = FHIROperationError(
            status_code=422,
            message="Validation failed",
            operation_outcome=outcome,
        )

        assert error.status_code == 422
        assert "Validation failed" in str(error)
        assert error.operation_outcome == outcome
