"""Tests unitaires pour le client FHIR.

Ce module teste le client HTTP async pour la communication avec HAPI FHIR,
incluant les operations CRUD, la gestion des erreurs et le pattern singleton.
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
    """Create a FHIR client instance for testing."""
    return FHIRClient(base_url="http://test-fhir:8080/fhir", timeout=30)


@pytest.fixture
def sample_fhir_patient():
    """Create a sample FHIR Patient for testing."""
    return FHIRPatient(
        id="patient-123",
        active=True,
        name=[{"family": "Test", "given": ["Patient"]}],
    )


@pytest.fixture
def sample_fhir_patient_json():
    """Sample FHIR Patient as JSON bytes."""
    return json.dumps(
        {
            "resourceType": "Patient",
            "id": "patient-123",
            "active": True,
            "name": [{"family": "Test", "given": ["Patient"]}],
        }
    ).encode()


@pytest.fixture
def sample_fhir_practitioner():
    """Create a sample FHIR Practitioner for testing."""
    return FHIRPractitioner(
        id="practitioner-456",
        active=True,
        name=[{"family": "Doctor", "given": ["Test"]}],
    )


@pytest.fixture
def sample_fhir_practitioner_json():
    """Sample FHIR Practitioner as JSON bytes."""
    return json.dumps(
        {
            "resourceType": "Practitioner",
            "id": "practitioner-456",
            "active": True,
            "name": [{"family": "Doctor", "given": ["Test"]}],
        }
    ).encode()


@pytest.fixture
def sample_bundle_json():
    """Sample FHIR Bundle as JSON bytes."""
    return json.dumps(
        {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 2,
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "patient-1",
                        "active": True,
                    }
                },
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "patient-2",
                        "active": True,
                    }
                },
            ],
        }
    ).encode()


@pytest.fixture
def empty_bundle_json():
    """Empty FHIR Bundle as JSON bytes."""
    return json.dumps(
        {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 0,
            "entry": [],
        }
    ).encode()


@pytest.fixture
def mock_response():
    """Create a mock httpx Response."""

    def _create_response(
        status_code: int, content: bytes | None = None, json_data: dict | None = None
    ):
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        response.content = content or b""
        response.text = content.decode() if content else ""
        if json_data:
            response.json.return_value = json_data
        else:
            response.json.side_effect = json.JSONDecodeError("No JSON", "", 0)
        return response

    return _create_response


# =============================================================================
# Tests pour FHIRClient.__init__
# =============================================================================


class TestFHIRClientInit:
    """Tests pour l'initialisation du client FHIR."""

    def test_init_with_defaults(self):
        """Test initialisation avec valeurs par defaut."""
        with patch("app.infrastructure.fhir.client.fhir_settings") as mock_settings:
            mock_settings.HAPI_FHIR_BASE_URL = "http://default:8080/fhir"
            mock_settings.HAPI_FHIR_TIMEOUT = 30

            client = FHIRClient()

            assert client.base_url == "http://default:8080/fhir"
            assert client.timeout == 30
            assert client._client is None

    def test_init_with_custom_values(self):
        """Test initialisation avec valeurs personnalisees."""
        client = FHIRClient(base_url="http://custom:9090/fhir/", timeout=60)

        # Trailing slash should be stripped
        assert client.base_url == "http://custom:9090/fhir"
        assert client.timeout == 60

    def test_init_strips_trailing_slash(self):
        """Test que le trailing slash est supprime."""
        client = FHIRClient(base_url="http://test/fhir///")

        assert client.base_url == "http://test/fhir"


# =============================================================================
# Tests pour FHIRClient._get_client
# =============================================================================


class TestFHIRClientGetClient:
    """Tests pour _get_client()."""

    @pytest.mark.asyncio
    async def test_get_client_creates_new(self, fhir_client):
        """Test creation d'un nouveau client HTTP."""
        assert fhir_client._client is None

        client = await fhir_client._get_client()

        assert client is not None
        assert isinstance(client, httpx.AsyncClient)
        await fhir_client.close()

    @pytest.mark.asyncio
    async def test_get_client_reuses_existing(self, fhir_client):
        """Test reutilisation du client existant."""
        client1 = await fhir_client._get_client()
        client2 = await fhir_client._get_client()

        assert client1 is client2
        await fhir_client.close()

    @pytest.mark.asyncio
    async def test_get_client_creates_new_if_closed(self, fhir_client):
        """Test creation d'un nouveau client si l'ancien est ferme."""
        client1 = await fhir_client._get_client()
        await fhir_client.close()

        client2 = await fhir_client._get_client()

        assert client2 is not None
        assert client1 is not client2
        await fhir_client.close()


# =============================================================================
# Tests pour FHIRClient.create
# =============================================================================


class TestFHIRClientCreate:
    """Tests pour create()."""

    @pytest.mark.asyncio
    async def test_create_patient_success(
        self, fhir_client, sample_fhir_patient, sample_fhir_patient_json, mock_response
    ):
        """Test creation d'un patient reussie."""
        mock_resp = mock_response(201, sample_fhir_patient_json)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.create(sample_fhir_patient)

            assert result.id == "patient-123"
            mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_practitioner_success(
        self, fhir_client, sample_fhir_practitioner, sample_fhir_practitioner_json, mock_response
    ):
        """Test creation d'un practitioner reussie."""
        mock_resp = mock_response(201, sample_fhir_practitioner_json)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.create(sample_fhir_practitioner)

            assert result.id == "practitioner-456"

    @pytest.mark.asyncio
    async def test_create_connection_error(self, fhir_client, sample_fhir_patient):
        """Test erreur de connexion lors de la creation."""
        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_get.return_value = mock_http

            with pytest.raises(FHIRConnectionError) as exc_info:
                await fhir_client.create(sample_fhir_patient)

            assert "Failed to connect to FHIR server" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_timeout_error(self, fhir_client, sample_fhir_patient):
        """Test timeout lors de la creation."""
        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_get.return_value = mock_http

            with pytest.raises(FHIRConnectionError) as exc_info:
                await fhir_client.create(sample_fhir_patient)

            assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_operation_error(self, fhir_client, sample_fhir_patient, mock_response):
        """Test erreur operation lors de la creation."""
        error_response = mock_response(
            400,
            b'{"issue": [{"severity": "error", "diagnostics": "Invalid resource"}]}',
            {"issue": [{"severity": "error", "diagnostics": "Invalid resource"}]},
        )

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=error_response)
            mock_get.return_value = mock_http

            with pytest.raises(FHIROperationError) as exc_info:
                await fhir_client.create(sample_fhir_patient)

            assert exc_info.value.status_code == 400


# =============================================================================
# Tests pour FHIRClient.read
# =============================================================================


class TestFHIRClientRead:
    """Tests pour read()."""

    @pytest.mark.asyncio
    async def test_read_patient_found(self, fhir_client, sample_fhir_patient_json, mock_response):
        """Test lecture d'un patient existant."""
        mock_resp = mock_response(200, sample_fhir_patient_json)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.read("Patient", "patient-123")

            assert result is not None
            assert result.id == "patient-123"
            mock_http.get.assert_called_once_with("/Patient/patient-123")

    @pytest.mark.asyncio
    async def test_read_practitioner_found(
        self, fhir_client, sample_fhir_practitioner_json, mock_response
    ):
        """Test lecture d'un practitioner existant."""
        mock_resp = mock_response(200, sample_fhir_practitioner_json)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.read("Practitioner", "practitioner-456")

            assert result is not None
            assert result.id == "practitioner-456"

    @pytest.mark.asyncio
    async def test_read_not_found(self, fhir_client, mock_response):
        """Test lecture d'une ressource inexistante."""
        mock_resp = mock_response(404, b"Not found")

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.read("Patient", "unknown-id")

            assert result is None

    @pytest.mark.asyncio
    async def test_read_connection_error(self, fhir_client):
        """Test erreur de connexion lors de la lecture."""
        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_get.return_value = mock_http

            with pytest.raises(FHIRConnectionError):
                await fhir_client.read("Patient", "patient-123")


# =============================================================================
# Tests pour FHIRClient.update
# =============================================================================


class TestFHIRClientUpdate:
    """Tests pour update()."""

    @pytest.mark.asyncio
    async def test_update_success(
        self, fhir_client, sample_fhir_patient, sample_fhir_patient_json, mock_response
    ):
        """Test mise a jour reussie."""
        mock_resp = mock_response(200, sample_fhir_patient_json)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.put = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.update(sample_fhir_patient)

            assert result.id == "patient-123"
            mock_http.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_not_found(self, fhir_client, sample_fhir_patient, mock_response):
        """Test mise a jour d'une ressource inexistante."""
        mock_resp = mock_response(404, b"Not found")

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.put = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            with pytest.raises(FHIRResourceNotFoundError) as exc_info:
                await fhir_client.update(sample_fhir_patient)

            assert exc_info.value.resource_type == "Patient"
            assert exc_info.value.resource_id == "patient-123"

    @pytest.mark.asyncio
    async def test_update_connection_error(self, fhir_client, sample_fhir_patient):
        """Test erreur de connexion lors de la mise a jour."""
        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.put = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_get.return_value = mock_http

            with pytest.raises(FHIRConnectionError):
                await fhir_client.update(sample_fhir_patient)


# =============================================================================
# Tests pour FHIRClient.search
# =============================================================================


class TestFHIRClientSearch:
    """Tests pour search()."""

    @pytest.mark.asyncio
    async def test_search_with_results(self, fhir_client, sample_bundle_json, mock_response):
        """Test recherche avec resultats."""
        mock_resp = mock_response(200, sample_bundle_json)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.search("Patient", {"active": "true"})

            assert isinstance(result, Bundle)
            assert result.total == 2
            assert len(result.entry) == 2

    @pytest.mark.asyncio
    async def test_search_empty_results(self, fhir_client, empty_bundle_json, mock_response):
        """Test recherche sans resultats."""
        mock_resp = mock_response(200, empty_bundle_json)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.search("Patient")

            assert isinstance(result, Bundle)
            assert result.total == 0

    @pytest.mark.asyncio
    async def test_search_with_params(self, fhir_client, sample_bundle_json, mock_response):
        """Test recherche avec parametres."""
        mock_resp = mock_response(200, sample_bundle_json)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            await fhir_client.search("Patient", {"name": "Test", "active": "true"})

            mock_http.get.assert_called_once_with(
                "/Patient",
                params={"name": "Test", "active": "true"},
            )

    @pytest.mark.asyncio
    async def test_search_connection_error(self, fhir_client):
        """Test erreur de connexion lors de la recherche."""
        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_get.return_value = mock_http

            with pytest.raises(FHIRConnectionError):
                await fhir_client.search("Patient")


# =============================================================================
# Tests pour FHIRClient.search_by_identifier
# =============================================================================


class TestFHIRClientSearchByIdentifier:
    """Tests pour search_by_identifier()."""

    @pytest.mark.asyncio
    async def test_search_by_identifier_found(self, fhir_client, mock_response):
        """Test recherche par identifiant trouve."""
        bundle_with_entry = json.dumps(
            {
                "resourceType": "Bundle",
                "type": "searchset",
                "total": 1,
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Patient",
                            "id": "found-patient",
                            "active": True,
                        }
                    }
                ],
            }
        ).encode()
        mock_resp = mock_response(200, bundle_with_entry)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.search_by_identifier(
                "Patient",
                "https://keycloak.africare.app/realms/africare",
                "user-123",
            )

            assert result is not None
            assert result.id == "found-patient"

    @pytest.mark.asyncio
    async def test_search_by_identifier_not_found(
        self, fhir_client, empty_bundle_json, mock_response
    ):
        """Test recherche par identifiant non trouve."""
        mock_resp = mock_response(200, empty_bundle_json)

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get.return_value = mock_http

            result = await fhir_client.search_by_identifier(
                "Patient",
                "https://keycloak.africare.app/realms/africare",
                "unknown-user",
            )

            assert result is None


# =============================================================================
# Tests pour FHIRClient._handle_error_response
# =============================================================================


class TestFHIRClientHandleErrorResponse:
    """Tests pour _handle_error_response()."""

    def test_handle_error_with_json(self, fhir_client, mock_response):
        """Test gestion erreur avec reponse JSON."""
        error_resp = mock_response(
            400,
            b'{"issue": "test"}',
            {"issue": "test"},
        )
        mock_span = MagicMock()

        with pytest.raises(FHIROperationError) as exc_info:
            fhir_client._handle_error_response(error_resp, mock_span)

        assert exc_info.value.status_code == 400
        assert exc_info.value.operation_outcome == {"issue": "test"}

    def test_handle_error_without_json(self, fhir_client, mock_response):
        """Test gestion erreur sans JSON valide."""
        error_resp = mock_response(500, b"Internal Server Error")
        mock_span = MagicMock()

        with pytest.raises(FHIROperationError) as exc_info:
            fhir_client._handle_error_response(error_resp, mock_span)

        assert exc_info.value.status_code == 500
        assert "text" in exc_info.value.operation_outcome


# =============================================================================
# Tests pour FHIRClient.close
# =============================================================================


class TestFHIRClientClose:
    """Tests pour close()."""

    @pytest.mark.asyncio
    async def test_close_with_client(self, fhir_client):
        """Test fermeture avec client existant."""
        # Create a client first
        await fhir_client._get_client()
        assert fhir_client._client is not None

        await fhir_client.close()

        assert fhir_client._client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self, fhir_client):
        """Test fermeture sans client."""
        assert fhir_client._client is None

        await fhir_client.close()  # Should not raise

        assert fhir_client._client is None


# =============================================================================
# Tests pour le pattern Singleton
# =============================================================================


class TestSingletonPattern:
    """Tests pour les fonctions singleton."""

    @pytest.mark.asyncio
    async def test_initialize_fhir_client(self):
        """Test initialisation du singleton."""
        # Ensure clean state
        await close_fhir_client()

        client = await initialize_fhir_client(
            base_url="http://test:8080/fhir",
            timeout=30,
        )

        assert client is not None
        assert isinstance(client, FHIRClient)

        # Cleanup
        await close_fhir_client()

    @pytest.mark.asyncio
    async def test_get_fhir_client_after_init(self):
        """Test recuperation du singleton apres initialisation."""
        await close_fhir_client()
        await initialize_fhir_client(base_url="http://test:8080/fhir")

        client = get_fhir_client()

        assert client is not None
        assert isinstance(client, FHIRClient)

        await close_fhir_client()

    @pytest.mark.asyncio
    async def test_get_fhir_client_without_init(self):
        """Test recuperation du singleton sans initialisation."""
        await close_fhir_client()

        with pytest.raises(RuntimeError) as exc_info:
            get_fhir_client()

        assert "FHIR client not initialized" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_close_fhir_client(self):
        """Test fermeture du singleton."""
        await initialize_fhir_client(base_url="http://test:8080/fhir")

        await close_fhir_client()

        with pytest.raises(RuntimeError):
            get_fhir_client()

    @pytest.mark.asyncio
    async def test_close_fhir_client_when_none(self):
        """Test fermeture du singleton quand deja None."""
        await close_fhir_client()  # Ensure None

        await close_fhir_client()  # Should not raise

        with pytest.raises(RuntimeError):
            get_fhir_client()


# =============================================================================
# Tests pour les exceptions FHIR
# =============================================================================


class TestFHIRExceptions:
    """Tests pour les exceptions FHIR."""

    def test_fhir_connection_error(self):
        """Test FHIRConnectionError."""
        error = FHIRConnectionError("Connection failed", {"host": "localhost"})

        assert str(error) == "Connection failed"
        assert error.message == "Connection failed"
        assert error.details == {"host": "localhost"}

    def test_fhir_resource_not_found_error(self):
        """Test FHIRResourceNotFoundError."""
        error = FHIRResourceNotFoundError("Patient", "patient-123")

        assert "Patient/patient-123 not found" in str(error)
        assert error.resource_type == "Patient"
        assert error.resource_id == "patient-123"
        assert error.details["resource_type"] == "Patient"

    def test_fhir_operation_error(self):
        """Test FHIROperationError."""
        error = FHIROperationError(
            status_code=400,
            message="Validation failed",
            operation_outcome={"issue": [{"severity": "error"}]},
        )

        assert error.status_code == 400
        assert error.message == "Validation failed"
        assert error.operation_outcome == {"issue": [{"severity": "error"}]}


# =============================================================================
# Tests d'integration (avec vraies requetes mockees)
# =============================================================================


class TestFHIRClientIntegration:
    """Tests d'integration avec mock complet."""

    @pytest.mark.asyncio
    async def test_create_read_update_flow(self, fhir_client, mock_response):
        """Test flux complet create -> read -> update."""
        patient_json = json.dumps(
            {
                "resourceType": "Patient",
                "id": "flow-test-123",
                "active": True,
                "name": [{"family": "Flow", "given": ["Test"]}],
            }
        ).encode()

        with patch.object(fhir_client, "_get_client") as mock_get:
            mock_http = AsyncMock()
            mock_get.return_value = mock_http

            # Create
            mock_http.post = AsyncMock(return_value=mock_response(201, patient_json))
            patient = FHIRPatient(active=True, name=[{"family": "Flow", "given": ["Test"]}])
            created = await fhir_client.create(patient)
            assert created.id == "flow-test-123"

            # Read
            mock_http.get = AsyncMock(return_value=mock_response(200, patient_json))
            read = await fhir_client.read("Patient", "flow-test-123")
            assert read.id == "flow-test-123"

            # Update
            updated_json = json.dumps(
                {
                    "resourceType": "Patient",
                    "id": "flow-test-123",
                    "active": False,
                    "name": [{"family": "Flow", "given": ["Updated"]}],
                }
            ).encode()
            mock_http.put = AsyncMock(return_value=mock_response(200, updated_json))
            created.active = False
            updated = await fhir_client.update(created)
            assert updated.active is False
