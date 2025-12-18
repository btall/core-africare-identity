# Importer tous les modèles SQLAlchemy ici pour qu'Alembic puisse les détecter
from .gdpr_metadata import PatientGdprMetadata, ProfessionalGdprMetadata
from .patient import Patient
from .professional import Professional

__all__ = [
    "Patient",
    "PatientGdprMetadata",
    "Professional",
    "ProfessionalGdprMetadata",
]
