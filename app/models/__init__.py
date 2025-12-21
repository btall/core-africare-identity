# Modèles SQLAlchemy pour core-africare-identity
#
# Architecture hybride FHIR + PostgreSQL:
# - Données démographiques: HAPI FHIR (Patient/Practitioner resources)
# - Métadonnées GDPR: PostgreSQL (patient_gdpr_metadata, professional_gdpr_metadata)
#
# Les modèles Patient et Professional sont OBSOLÈTES.
# Les tables correspondantes ont été supprimées par la migration d5be1f5f6b77.
# Ces modèles sont conservés temporairement pour compatibilité avec:
# - app/api/v1/endpoints/admin_patients.py
# - app/api/v1/endpoints/admin_professionals.py
# - app/services/anonymization_scheduler.py
# - app/services/patient_anonymization_scheduler.py
# - app/services/statistics_service.py
#
# TODO: Migrer ces fichiers vers l'architecture FHIR + GDPR metadata

# Modèles actifs (FHIR hybrid architecture)
from .gdpr_metadata import PatientGdprMetadata, ProfessionalGdprMetadata

# Modèles obsolètes (tables supprimées - migration d5be1f5f6b77)
# Conservés uniquement pour compatibilité avec admin_patients.py et schedulers
from .patient import Patient
from .professional import Professional

__all__ = [
    "Patient",  # OBSOLÈTE - table supprimée, conservé pour compatibilité
    "PatientGdprMetadata",
    "Professional",  # OBSOLÈTE - table supprimée, conservé pour compatibilité
    "ProfessionalGdprMetadata",
]
