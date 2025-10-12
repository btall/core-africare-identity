# Importer tous les modèles SQLAlchemy ici pour qu'Alembic puisse les détecter
from .patient import Patient
from .professional import Professional

__all__ = [
    "Patient",
    "Professional",
]
