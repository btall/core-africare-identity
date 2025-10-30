"""
Tests unitaires pour le middleware RFC 9457 Problem Details.
"""

from datetime import datetime

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastapi_errors_rfc9457 import RFC9457Config, setup_rfc9457_handlers
from pydantic import BaseModel, field_validator

from app.core.exceptions import (
    AfriCareException,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.schemas import (
    COMMON_RESPONSES,
    ConflictErrorResponse,
    ProblemDetailResponse,
    ValidationErrorResponse,
)


class ExampleRequest(BaseModel):
    """Modèle de requête pour les tests de validation."""

    name: str
    age: int

    @field_validator("age")
    @classmethod
    def validate_age(cls, v: int) -> int:
        if v < 0 or v > 150:
            raise ValueError("Age must be between 0 and 150")
        return v


# Application de test avec exception handlers RFC 9457
app = FastAPI()
config = RFC9457Config(
    base_url="about:blank",
    include_trace_id=True,
    expose_internal_errors=False,
    include_error_pages=False,  # Disable for tests
)
setup_rfc9457_handlers(app, config=config)


@app.get("/test/success")
async def endpoint_success():
    """Endpoint de succès."""
    return {"message": "success"}


@app.get("/test/http-exception")
async def endpoint_http_exception():
    """Endpoint déclenchant une HTTPException standard."""
    raise HTTPException(status_code=404, detail="Resource not found")


@app.get("/test/africare-exception")
async def endpoint_africare_exception():
    """Endpoint déclenchant une AfriCareException."""
    raise NotFoundError(
        detail="User not found",
        resource_type="user",
        resource_id="12345",
    )


@app.get("/test/validation-error")
async def endpoint_validation_error():
    """Endpoint déclenchant une ValidationError."""
    raise ValidationError(
        detail="Invalid input",
        errors=[{"loc": ["body", "email"], "msg": "Invalid email format", "type": "value_error"}],
    )


@app.get("/test/unauthorized")
async def endpoint_unauthorized():
    """Endpoint déclenchant une UnauthorizedError."""
    raise UnauthorizedError()


@app.get("/test/forbidden")
async def endpoint_forbidden():
    """Endpoint déclenchant une ForbiddenError."""
    raise ForbiddenError(detail="Insufficient permissions")


@app.get("/test/conflict")
async def endpoint_conflict():
    """Endpoint déclenchant une ConflictError."""
    raise ConflictError(
        detail="Email already exists",
        conflicting_resource="user/12345",
    )


@app.get("/test/internal-error")
async def endpoint_internal_error():
    """Endpoint déclenchant une erreur 500 générique."""
    raise Exception("Unexpected error occurred")


@app.post("/test/request-validation")
async def endpoint_request_validation(data: ExampleRequest):
    """Endpoint pour tester la validation Pydantic."""
    return {"message": "validated", "data": data.model_dump()}


client = TestClient(app, raise_server_exceptions=False)


class TestProblemDetailsMiddleware:
    """Tests pour le middleware RFC 9457."""

    def test_successful_request(self):
        """Test qu'une requête réussie n'est pas interceptée."""
        response = client.get("/test/success")
        assert response.status_code == 200
        assert response.json() == {"message": "success"}

    def test_http_exception_conversion(self):
        """Test conversion HTTPException vers RFC 9457."""
        response = client.get("/test/http-exception")

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

        data = response.json()
        # When base_url="about:blank", the library auto-detects from request
        assert data["type"] == "http://testserver/errors/not-found.html"
        assert data["title"] == "Not Found"
        assert data["status"] == 404
        assert data["detail"] == "Resource not found"
        assert data["instance"] == "/test/http-exception"
        # trace_id is optional (present only if OpenTelemetry is active and recording)

    def test_africare_exception_conversion(self):
        """Test conversion AfriCareException vers RFC 9457."""
        response = client.get("/test/africare-exception")

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"

        data = response.json()
        # When base_url="about:blank", the library auto-detects from request
        assert data["type"] == "http://testserver/errors/not-found.html"
        assert data["title"] == "Not Found"
        assert data["status"] == 404
        assert data["detail"] == "User not found"
        assert data["instance"] == "/test/africare-exception"
        assert data["resource_type"] == "user"
        assert data["resource_id"] == "12345"
        # trace_id is optional (present only if OpenTelemetry is active and recording)

    def test_validation_error(self):
        """Test conversion ValidationError vers RFC 9457."""
        response = client.get("/test/validation-error")

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"

        data = response.json()
        # When base_url="about:blank", the library auto-detects from request
        assert data["type"] == "http://testserver/errors/validation-error.html"
        assert data["title"] == "Validation Error"
        assert data["status"] == 400
        assert data["detail"] == "Invalid input"
        assert len(data["errors"]) == 1
        assert data["errors"][0]["loc"] == ["body", "email"]
        # trace_id is optional (present only if OpenTelemetry is active and recording)

    def test_unauthorized_error(self):
        """Test UnauthorizedError avec WWW-Authenticate header."""
        response = client.get("/test/unauthorized")

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"
        assert "www-authenticate" in response.headers

        data = response.json()
        # When base_url="about:blank", the library auto-detects from request
        assert data["type"] == "http://testserver/errors/unauthorized.html"
        assert data["title"] == "Unauthorized"
        assert data["status"] == 401
        # trace_id is optional (present only if OpenTelemetry is active and recording)

    def test_forbidden_error(self):
        """Test ForbiddenError."""
        response = client.get("/test/forbidden")

        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

        data = response.json()
        # When base_url="about:blank", the library auto-detects from request
        assert data["type"] == "http://testserver/errors/forbidden.html"
        assert data["title"] == "Forbidden"
        assert data["status"] == 403
        assert data["detail"] == "Insufficient permissions"
        # trace_id is optional (present only if OpenTelemetry is active and recording)

    def test_conflict_error(self):
        """Test ConflictError avec extension."""
        response = client.get("/test/conflict")

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"

        data = response.json()
        # When base_url="about:blank", the library auto-detects from request
        assert data["type"] == "http://testserver/errors/conflict.html"
        assert data["title"] == "Conflict"
        assert data["status"] == 409
        assert data["detail"] == "Email already exists"
        assert data["conflicting_resource"] == "user/12345"
        # trace_id is optional (present only if OpenTelemetry is active and recording)

    def test_internal_server_error(self):
        """Test conversion exception générique vers erreur 500."""
        response = client.get("/test/internal-error")

        assert response.status_code == 500
        assert response.headers["content-type"] == "application/problem+json"

        data = response.json()
        # When base_url="about:blank", the library auto-detects from request
        assert data["type"] == "http://testserver/errors/internal-server-error.html"
        assert data["title"] == "Internal Server Error"
        assert data["status"] == 500
        # trace_id is optional (present only if OpenTelemetry is active and recording)
        # Le détail ne doit PAS exposer l'erreur interne
        assert "Unexpected error occurred" not in data["detail"]

    def test_request_validation_error(self):
        """Test RequestValidationError de Pydantic."""
        response = client.post(
            "/test/request-validation",
            json={"name": "John", "age": 200},  # Age invalide
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

        data = response.json()
        # When base_url="about:blank", the library auto-detects from request
        assert data["type"] == "http://testserver/errors/validation-error.html"
        assert data["title"] == "Validation Error"
        assert data["status"] == 422
        assert "errors" in data
        assert len(data["errors"]) > 0
        # trace_id is optional (present only if OpenTelemetry is active and recording)
        # Vérifier qu'on a bien une erreur sur le champ "age"
        age_errors = [e for e in data["errors"] if "age" in str(e["loc"])]
        assert len(age_errors) > 0

    def test_request_validation_missing_field(self):
        """Test RequestValidationError avec champ manquant."""
        response = client.post(
            "/test/request-validation",
            json={"name": "John"},  # Champ age manquant
        )

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"

        data = response.json()
        assert data["status"] == 422
        assert "errors" in data
        # trace_id is optional (present only if OpenTelemetry is active and recording)


class TestAfriCareExceptions:
    """Tests pour les exceptions AfriCare pré-configurées."""

    def test_validation_error_creation(self):
        """Test création ValidationError."""
        exc = ValidationError(
            detail="Invalid email format",
            errors=[{"loc": ["body", "email"], "msg": "Invalid format", "type": "value_error"}],
        )

        assert exc.status_code == 400
        assert exc.problem_detail.title == "Validation Error"
        # When using default config (base_url="about:blank"), type is "about:blank"
        assert exc.problem_detail.type == "about:blank"

        result = exc.to_dict()
        assert result["errors"] == [
            {"loc": ["body", "email"], "msg": "Invalid format", "type": "value_error"}
        ]

    def test_not_found_error_creation(self):
        """Test création NotFoundError avec extensions."""
        exc = NotFoundError(
            detail="User not found",
            resource_type="user",
            resource_id="12345",
            instance="/api/v1/users/12345",
        )

        assert exc.status_code == 404
        result = exc.to_dict()
        assert result["resource_type"] == "user"
        assert result["resource_id"] == "12345"
        assert result["instance"] == "/api/v1/users/12345"

    def test_internal_server_error_with_trace(self):
        """Test InternalServerError avec trace_id."""
        exc = InternalServerError(
            detail="Database connection failed",
            trace_id="abc123def456",
        )

        assert exc.status_code == 500
        result = exc.to_dict()
        assert result["trace_id"] == "abc123def456"
        assert "Database connection failed" in result["detail"]

    def test_custom_africare_exception(self):
        """Test création d'une AfriCareException personnalisée."""
        exc = AfriCareException(
            status_code=418,
            title="I'm a teapot",
            detail="Cannot brew coffee",
            type_uri="https://africare.app/errors/teapot",
            instance="/api/v1/coffee",
            brew_type="espresso",  # Extension personnalisée
        )

        assert exc.status_code == 418
        result = exc.to_dict()
        assert result["type"] == "https://africare.app/errors/teapot"
        assert result["brew_type"] == "espresso"


class TestOpenAPISchemas:
    """Tests pour les schémas OpenAPI RFC 9457."""

    def test_problem_detail_response_model(self):
        """Test modèle ProblemDetailResponse."""
        problem = ProblemDetailResponse(
            type="https://africare.app/errors/test",
            title="Test Error",
            status=400,
            detail="Test detail",
            instance="/api/v1/test",
            trace_id="abc123",
            timestamp="2025-10-09T09:50:56.209911+00:00",
        )

        assert problem.type == "https://africare.app/errors/test"
        assert problem.title == "Test Error"
        assert problem.status == 400
        assert problem.detail == "Test detail"
        assert problem.instance == "/api/v1/test"
        assert problem.trace_id == "abc123"
        assert problem.timestamp == "2025-10-09T09:50:56.209911+00:00"

    def test_validation_error_response_model(self):
        """Test modèle ValidationErrorResponse."""
        validation_error = ValidationErrorResponse(
            type="https://africare.app/errors/validation-error",
            title="Validation Error",
            status=422,
            detail="2 validation error(s) detected",
            instance="/api/v1/users",
            trace_id="abc123",
            timestamp="2025-10-09T09:50:56.209911+00:00",
            errors=[{"loc": ["body", "email"], "msg": "Invalid email", "type": "value_error"}],
        )

        assert validation_error.status == 422
        assert len(validation_error.errors) == 1
        assert validation_error.errors[0]["loc"] == ["body", "email"]

    def test_conflict_error_response_model(self):
        """Test modèle ConflictErrorResponse."""
        conflict_error = ConflictErrorResponse(
            type="https://africare.app/errors/conflict",
            title="Conflict",
            status=409,
            detail="Email already exists",
            instance="/api/v1/users",
            trace_id="abc123",
            timestamp="2025-10-09T09:50:56.209911+00:00",
            conflicting_resource="/api/v1/users/67890",
        )

        assert conflict_error.status == 409
        assert conflict_error.conflicting_resource == "/api/v1/users/67890"

    def test_common_responses_structure(self):
        """Test structure de COMMON_RESPONSES."""
        assert 400 in COMMON_RESPONSES
        assert 401 in COMMON_RESPONSES
        assert 403 in COMMON_RESPONSES
        assert 404 in COMMON_RESPONSES
        assert 409 in COMMON_RESPONSES
        assert 422 in COMMON_RESPONSES
        assert 500 in COMMON_RESPONSES

        # Vérifier structure de chaque réponse
        for _status_code, response_spec in COMMON_RESPONSES.items():
            assert "model" in response_spec
            assert "description" in response_spec
            assert "content" in response_spec
            assert "application/problem+json" in response_spec["content"]
            # Le nouveau module utilise "examples" au lieu de "example"
            assert "examples" in response_spec["content"]["application/problem+json"]

    def test_common_responses_with_api_router(self):
        """Test que COMMON_RESPONSES s'applique correctement à un APIRouter."""
        router = APIRouter(responses=COMMON_RESPONSES)

        @router.get("/test-endpoint")
        async def test_endpoint():
            return {"message": "test"}

        # Vérifier que le router a bien les réponses communes
        assert router.responses == COMMON_RESPONSES

    def test_common_responses_merge_with_endpoint_responses(self):
        """Test fusion des réponses communes avec réponses spécifiques."""
        app_test = FastAPI()
        router = APIRouter(responses=COMMON_RESPONSES)

        @router.get(
            "/test-merge",
            responses={
                201: {"description": "Created"},
                503: {"description": "Service Unavailable"},
            },
        )
        async def test_merge():
            return {"message": "test"}

        app_test.include_router(router)

        # Créer un client de test
        client_test = TestClient(app_test)

        # Vérifier que l'endpoint existe
        response = client_test.get("/test-merge")
        assert response.status_code == 200

        # Vérifier OpenAPI schema
        openapi_schema = app_test.openapi()
        endpoint_responses = openapi_schema["paths"]["/test-merge"]["get"]["responses"]

        # Vérifier que les réponses communes sont présentes
        assert "400" in endpoint_responses
        assert "404" in endpoint_responses
        assert "409" in endpoint_responses
        assert "422" in endpoint_responses

        # Vérifier que les réponses spécifiques sont aussi présentes
        assert "201" in endpoint_responses
        assert "503" in endpoint_responses


@pytest.mark.skip(reason="Timestamps not implemented in fastapi-errors-rfc9457 library")
class TestTimestampUTC:
    """Tests spécifiques pour le champ timestamp UTC."""

    def test_timestamp_format_iso8601_with_timezone(self):
        """Test que le timestamp est bien au format ISO 8601 avec timezone."""
        response = client.get("/test/http-exception")

        data = response.json()
        assert "timestamp" in data

        # Parser le timestamp ISO 8601
        timestamp = datetime.fromisoformat(data["timestamp"])

        # Vérifier que la timezone est présente
        assert timestamp.tzinfo is not None

        # Vérifier format attendu (avec +00:00 pour UTC)
        assert "+00:00" in data["timestamp"]

    def test_timestamp_present_in_all_error_types(self):
        """Test que timestamp est présent dans tous les types d'erreur."""
        test_endpoints = [
            "/test/http-exception",
            "/test/africare-exception",
            "/test/validation-error",
            "/test/unauthorized",
            "/test/forbidden",
            "/test/conflict",
            "/test/internal-error",
        ]

        for endpoint in test_endpoints:
            response = client.get(endpoint)
            data = response.json()
            assert "timestamp" in data, f"timestamp manquant pour {endpoint}"
            # Vérifier que c'est un timestamp valide
            timestamp = datetime.fromisoformat(data["timestamp"])
            assert timestamp.tzinfo is not None

    def test_timestamp_in_request_validation_error(self):
        """Test timestamp dans RequestValidationError."""
        response = client.post("/test/request-validation", json={"name": "John", "age": 200})

        data = response.json()
        assert "timestamp" in data
        timestamp = datetime.fromisoformat(data["timestamp"])
        assert timestamp.tzinfo is not None
        assert "+00:00" in data["timestamp"]
