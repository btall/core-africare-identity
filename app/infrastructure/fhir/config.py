"""Configuration for HAPI FHIR server connection."""

from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings


class FHIRSettings(BaseSettings):
    """FHIR server configuration settings.

    Settings can be overridden via environment variables.
    """

    HAPI_FHIR_BASE_URL: AnyHttpUrl = "http://hapi-fhir:8080/fhir"
    HAPI_FHIR_TIMEOUT: int = 30
    HAPI_FHIR_RETRY_ATTEMPTS: int = 3
    HAPI_FHIR_RETRY_DELAY: float = 1.0

    model_config = {
        "env_prefix": "",
        "case_sensitive": True,
    }


fhir_settings = FHIRSettings()
