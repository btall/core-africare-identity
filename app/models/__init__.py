# Importer tous les modèles SQLAlchemy ici pour qu'Alembic puisse les détecter
from .patient import Patient  # noqa: F401
from .professional import Professional  # noqa: F401

__all__ = [
    "Patient",
    "Professional",
]
