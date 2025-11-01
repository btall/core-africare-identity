"""Tests unitaires pour les exceptions custom RFC 9457."""

import pytest

from app.core.exceptions import (
    AnonymizationError,
    KeycloakServiceError,
    ProblemDetail,
)


class TestKeycloakServiceError:
    """Tests pour KeycloakServiceError."""

    def test_keycloak_service_error_creation(self):
        """Test création exception Keycloak avec RFC 9457."""
        exc = KeycloakServiceError(
            detail="Cannot retrieve user roles from Keycloak",
            instance="/api/v1/webhooks",
        )

        assert exc.status_code == 503
        assert exc.problem_detail.title == "Service Unavailable"
        assert exc.problem_detail.detail == "Cannot retrieve user roles from Keycloak"
        assert exc.problem_detail.type is not None  # Type URI fourni par le package
        assert exc.problem_detail.instance == "/api/v1/webhooks"

    def test_keycloak_service_error_with_custom_message(self):
        """Test exception Keycloak avec message personnalisé."""
        exc = KeycloakServiceError(
            detail="Connection timeout to Keycloak server",
        )

        assert exc.problem_detail.detail == "Connection timeout to Keycloak server"
        assert exc.status_code == 503

    def test_keycloak_service_error_http_response(self):
        """Test que l'exception génère une réponse HTTP correcte."""
        exc = KeycloakServiceError(detail="Test error")

        # Vérifier que c'est une HTTPException compatible FastAPI
        assert hasattr(exc, "status_code")
        assert hasattr(exc, "problem_detail")
        assert isinstance(exc.problem_detail, ProblemDetail)


class TestAnonymizationError:
    """Tests pour AnonymizationError."""

    def test_anonymization_error_creation(self):
        """Test création exception anonymisation avec détails RGPD."""
        exc = AnonymizationError(
            detail="Failed to anonymize patient data: encryption error",
            instance="/api/v1/patients/123/anonymize",
        )

        assert exc.status_code == 500
        assert exc.problem_detail.title == "Internal Server Error"
        assert exc.problem_detail.detail == ("Failed to anonymize patient data: encryption error")
        assert exc.problem_detail.type is not None  # Type URI fourni par le package
        assert exc.problem_detail.instance == "/api/v1/patients/123/anonymize"

    def test_anonymization_error_with_entity_type(self):
        """Test exception anonymisation avec type d'entité."""
        exc = AnonymizationError(
            detail="Cannot hash professional credentials",
        )

        assert "Cannot hash professional credentials" in exc.problem_detail.detail
        assert exc.status_code == 500

    def test_anonymization_error_http_response(self):
        """Test que l'exception génère une réponse HTTP correcte."""
        exc = AnonymizationError(detail="GDPR compliance error")

        # Vérifier compatibilité FastAPI
        assert hasattr(exc, "status_code")
        assert hasattr(exc, "problem_detail")
        assert isinstance(exc.problem_detail, ProblemDetail)
        assert exc.problem_detail.title == "Internal Server Error"


class TestExceptionInheritance:
    """Tests pour l'héritage et la compatibilité des exceptions."""

    def test_keycloak_error_is_rfc9457_compliant(self):
        """Test que KeycloakServiceError respecte RFC 9457."""
        exc = KeycloakServiceError(detail="Test")

        # Doit avoir tous les champs RFC 9457
        assert hasattr(exc.problem_detail, "type")
        assert hasattr(exc.problem_detail, "title")
        assert hasattr(exc.problem_detail, "status")
        assert hasattr(exc.problem_detail, "detail")
        assert hasattr(exc.problem_detail, "instance")

    def test_anonymization_error_is_rfc9457_compliant(self):
        """Test que AnonymizationError respecte RFC 9457."""
        exc = AnonymizationError(detail="Test")

        # Doit avoir tous les champs RFC 9457
        assert hasattr(exc.problem_detail, "type")
        assert hasattr(exc.problem_detail, "title")
        assert hasattr(exc.problem_detail, "status")
        assert hasattr(exc.problem_detail, "detail")
        assert hasattr(exc.problem_detail, "instance")

    def test_error_can_be_raised_and_caught(self):
        """Test que les exceptions peuvent être levées et capturées."""
        with pytest.raises(KeycloakServiceError) as exc_info:
            raise KeycloakServiceError(detail="Test error")

        assert exc_info.value.status_code == 503
        assert "Test error" in exc_info.value.problem_detail.detail

    def test_anonymization_error_can_be_raised_and_caught(self):
        """Test que AnonymizationError peut être levée et capturée."""
        with pytest.raises(AnonymizationError) as exc_info:
            raise AnonymizationError(detail="GDPR error")

        assert exc_info.value.status_code == 500
        assert "GDPR error" in exc_info.value.problem_detail.detail
