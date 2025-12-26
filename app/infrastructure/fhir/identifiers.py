"""FHIR identifier systems and extension URLs for AfriCare.

These URIs follow FHIR conventions for system identifiers:
- Official systems use well-known URIs
- Custom extensions use the AfriCare namespace
"""

# Keycloak authentication system
KEYCLOAK_SYSTEM = "https://keycloak.africare.app/realms/africare"

# Senegalese national identification
NATIONAL_ID_SYSTEM = "http://senegal.gov.sn/nin"

# Professional license (Ordre National des Medecins du Senegal)
PROFESSIONAL_LICENSE_SYSTEM = "http://senegal.gov.sn/professional-license"

# Custom extensions for AfriCare-specific data
GPS_EXTENSION_URL = "https://africare.app/fhir/extensions/gps-location"
FACILITY_EXTENSION_URL = "https://africare.app/fhir/extensions/facility-info"
VERIFICATION_EXTENSION_URL = "https://africare.app/fhir/extensions/verification-status"
