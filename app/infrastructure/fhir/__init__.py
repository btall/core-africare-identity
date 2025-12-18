"""FHIR integration package for HAPI FHIR server communication."""

from app.infrastructure.fhir.client import FHIRClient
from app.infrastructure.fhir.config import fhir_settings
from app.infrastructure.fhir.identifiers import (
    GPS_EXTENSION_URL,
    KEYCLOAK_SYSTEM,
    NATIONAL_ID_SYSTEM,
    PROFESSIONAL_LICENSE_SYSTEM,
)

__all__ = [
    "GPS_EXTENSION_URL",
    "KEYCLOAK_SYSTEM",
    "NATIONAL_ID_SYSTEM",
    "PROFESSIONAL_LICENSE_SYSTEM",
    "FHIRClient",
    "fhir_settings",
]
