"""Dependances FastAPI pour l'injection de services."""

from fastapi import Request

from app.infrastructure.fhir.client import FHIRClient


def get_fhir_client(request: Request) -> FHIRClient:
    """
    Recupere le client FHIR depuis l'etat de l'application.

    Le client est initialise dans le lifespan de l'application (main.py)
    et stocke dans app.state.fhir_client.

    Args:
        request: Request FastAPI contenant l'application

    Returns:
        Instance du client FHIR

    Raises:
        RuntimeError: Si le client FHIR n'est pas initialise
    """
    fhir_client = getattr(request.app.state, "fhir_client", None)
    if fhir_client is None:
        raise RuntimeError(
            "FHIR client not initialized. "
            "Ensure the application lifespan properly initializes app.state.fhir_client"
        )
    return fhir_client
