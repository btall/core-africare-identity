# Modèles SQLAlchemy pour core-africare-identity
#
# Architecture hybride FHIR + PostgreSQL (depuis migration d5be1f5f6b77):
# - Données démographiques: HAPI FHIR (Patient/Practitioner resources)
# - Métadonnées GDPR: PostgreSQL (patient_gdpr_metadata, professional_gdpr_metadata)
#
# MODÈLES ACTIFS:
# - PatientGdprMetadata: Métadonnées RGPD locales pour patients
# - ProfessionalGdprMetadata: Métadonnées RGPD locales pour professionnels
#
# MODÈLES OBSOLÈTES (tables supprimées):
# Patient et Professional sont conservés UNIQUEMENT pour:
# - scripts/migrate_to_fhir.py (migration de données historiques)
# - app/services/keycloak_sync_service.py (fonctions legacy _soft_delete, _anonymize)
# - Tests unitaires non migrés (marqués @pytest.mark.skip)
#
# Ces fichiers seront supprimés une fois que:
# 1. keycloak_sync_service.py n'utilise plus les modèles legacy
# 2. Les tests sont migrés vers PatientGdprMetadata/ProfessionalGdprMetadata
# 3. La migration de données historiques est terminée

# Modèles actifs (FHIR hybrid architecture)
from .gdpr_metadata import PatientGdprMetadata, ProfessionalGdprMetadata

# Modèles obsolètes - NE PAS UTILISER dans nouveau code
# Tables supprimées par migration d5be1f5f6b77
from .patient import Patient
from .professional import Professional

__all__ = [
    "Patient",  # OBSOLÈTE - conservé pour migration/tests legacy
    "PatientGdprMetadata",
    "Professional",  # OBSOLÈTE - conservé pour migration/tests legacy
    "ProfessionalGdprMetadata",
]
