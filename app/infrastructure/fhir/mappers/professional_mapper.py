"""Mapper bidirectionnel entre Pydantic Professional et FHIR Practitioner.

Ce module fournit la conversion entre les schemas Pydantic de Professional
et les ressources FHIR R4 Practitioner pour l'integration HAPI FHIR.
"""

from datetime import datetime

from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.extension import Extension
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.practitioner import Practitioner as FHIRPractitioner
from fhir.resources.practitioner import PractitionerCommunication, PractitionerQualification

from app.infrastructure.fhir.identifiers import (
    KEYCLOAK_SYSTEM,
    PROFESSIONAL_LICENSE_SYSTEM,
)
from app.schemas.professional import (
    ProfessionalCreate,
    ProfessionalListItem,
    ProfessionalResponse,
    ProfessionalUpdate,
)

# Extension URLs for custom fields
FACILITY_EXTENSION_URL = "https://africare.app/fhir/extensions/facility"
EXPERIENCE_EXTENSION_URL = "https://africare.app/fhir/extensions/years-of-experience"

# Professional type to FHIR code mapping
PROFESSIONAL_TYPE_CODES = {
    "physician": ("physician", "Physician"),
    "nurse": ("nurse", "Nurse"),
    "midwife": ("midwife", "Midwife"),
    "pharmacist": ("pharmacist", "Pharmacist"),
    "technician": ("technician", "Technician"),
    "other": ("other", "Other healthcare professional"),
}

# Title prefix mapping
TITLE_PREFIX_MAP = {
    "Dr": "Dr.",
    "Pr": "Prof.",
    "Inf": "RN",
    "Sage-femme": "MW",
    "Pharmacien": "PharmD",
    "Autre": "",
}


# =============================================================================
# Helper functions for extracting data from FHIR Practitioner
# =============================================================================


def _extract_identifiers(practitioner: FHIRPractitioner) -> dict:
    """Extract keycloak_user_id and professional_id from FHIR identifiers."""
    result = {"keycloak_user_id": None, "professional_id": None}

    if not practitioner.identifier:
        return result

    for identifier in practitioner.identifier:
        if identifier.system == KEYCLOAK_SYSTEM:
            result["keycloak_user_id"] = identifier.value
        elif identifier.system == PROFESSIONAL_LICENSE_SYSTEM:
            result["professional_id"] = identifier.value

    return result


def _extract_name(practitioner: FHIRPractitioner) -> dict:
    """Extract name components and title from FHIR HumanName."""
    result = {"first_name": "", "last_name": "", "title": "Dr"}

    if not practitioner.name or len(practitioner.name) == 0:
        return result

    name = practitioner.name[0]
    result["first_name"] = name.given[0] if name.given else ""
    result["last_name"] = name.family or ""

    # Extract title from prefix
    if name.prefix:
        prefix = name.prefix[0]
        # Reverse lookup from FHIR prefix to our title
        for title, fhir_prefix in TITLE_PREFIX_MAP.items():
            if fhir_prefix == prefix:
                result["title"] = title
                break

    return result


def _extract_telecom(practitioner: FHIRPractitioner) -> dict:
    """Extract contact information from FHIR telecom."""
    result = {"email": None, "phone": None, "phone_secondary": None}

    if not practitioner.telecom:
        return result

    phone_count = 0
    for telecom in practitioner.telecom:
        if telecom.system == "email":
            result["email"] = telecom.value
        elif telecom.system == "phone":
            if phone_count == 0:
                result["phone"] = telecom.value
            elif phone_count == 1:
                result["phone_secondary"] = telecom.value
            phone_count += 1

    return result


def _extract_qualification(practitioner: FHIRPractitioner) -> dict:
    """Extract specialty and professional type from FHIR qualifications."""
    result = {
        "specialty": "",
        "sub_specialty": None,
        "professional_type": "other",
        "qualifications": None,
    }

    if not practitioner.qualification:
        return result

    for qual in practitioner.qualification:
        if not qual.code or not qual.code.coding:
            continue

        for coding in qual.code.coding:
            # Primary specialty
            if coding.system == "http://africare.app/fhir/specialty":
                result["specialty"] = coding.display or coding.code or ""
            # Sub-specialty
            elif coding.system == "http://africare.app/fhir/sub-specialty":
                result["sub_specialty"] = coding.display or coding.code
            # Professional type
            elif coding.system == "http://africare.app/fhir/professional-type":
                code = coding.code
                if code in PROFESSIONAL_TYPE_CODES:
                    result["professional_type"] = code
            # Qualifications text
            elif coding.system == "http://africare.app/fhir/qualifications":
                result["qualifications"] = coding.display

    return result


def _extract_facility_sub_extensions(sub_extensions: list) -> dict:
    """Extract facility fields from nested sub-extensions."""
    field_mapping = {
        "name": "facility_name",
        "type": "facility_type",
        "address": "facility_address",
        "city": "facility_city",
        "region": "facility_region",
    }
    result = dict.fromkeys(field_mapping.values())

    for sub_ext in sub_extensions:
        if sub_ext.url in field_mapping:
            result[field_mapping[sub_ext.url]] = sub_ext.valueString

    return result


def _extract_facility(practitioner: FHIRPractitioner) -> dict:
    """Extract facility information from FHIR extensions."""
    default_result = {
        "facility_name": None,
        "facility_type": None,
        "facility_address": None,
        "facility_city": None,
        "facility_region": None,
    }

    if not practitioner.extension:
        return default_result

    for ext in practitioner.extension:
        if ext.url == FACILITY_EXTENSION_URL and ext.extension:
            return _extract_facility_sub_extensions(ext.extension)

    return default_result


def _extract_experience(practitioner: FHIRPractitioner) -> int | None:
    """Extract years of experience from FHIR extensions."""
    if not practitioner.extension:
        return None

    for ext in practitioner.extension:
        if ext.url == EXPERIENCE_EXTENSION_URL:
            return ext.valueInteger

    return None


def _extract_languages(practitioner: FHIRPractitioner) -> str:
    """Extract spoken languages from FHIR communication."""
    if not practitioner.communication:
        return "fr"

    languages = []
    for comm in practitioner.communication:
        if comm.language and comm.language.coding:
            for coding in comm.language.coding:
                if coding.code:
                    languages.append(coding.code)

    return ",".join(languages) if languages else "fr"


# =============================================================================
# Helper functions for building FHIR Practitioner components
# =============================================================================


def _build_identifiers(
    keycloak_user_id: str, professional_id: str | None = None
) -> list[Identifier]:
    """Build FHIR identifiers for Practitioner."""
    identifiers = [
        Identifier(
            system=KEYCLOAK_SYSTEM,
            value=keycloak_user_id,
            use="official",
        )
    ]

    if professional_id:
        identifiers.append(
            Identifier(
                system=PROFESSIONAL_LICENSE_SYSTEM,
                value=professional_id,
                use="official",
            )
        )

    return identifiers


def _build_name(first_name: str, last_name: str, title: str = "Dr") -> list[HumanName]:
    """Build FHIR HumanName for Practitioner."""
    prefix = TITLE_PREFIX_MAP.get(title, "")
    name_data = {
        "use": "official",
        "family": last_name,
        "given": [first_name],
    }

    if prefix:
        name_data["prefix"] = [prefix]

    return [HumanName(**name_data)]


def _build_telecom(
    email: str, phone: str, phone_secondary: str | None = None
) -> list[ContactPoint]:
    """Build FHIR telecom for Practitioner."""
    telecom = [
        ContactPoint(system="email", value=email, use="work", rank=1),
        ContactPoint(system="phone", value=phone, use="work", rank=1),
    ]

    if phone_secondary:
        telecom.append(ContactPoint(system="phone", value=phone_secondary, use="work", rank=2))

    return telecom


def _build_qualifications(
    specialty: str,
    professional_type: str,
    sub_specialty: str | None = None,
    qualifications: str | None = None,
) -> list[PractitionerQualification]:
    """Build FHIR qualifications for Practitioner."""
    quals = []

    # Primary specialty
    quals.append(
        PractitionerQualification(
            code=CodeableConcept(
                coding=[
                    Coding(
                        system="http://africare.app/fhir/specialty",
                        code=specialty.lower().replace(" ", "-"),
                        display=specialty,
                    )
                ]
            )
        )
    )

    # Professional type
    type_code, type_display = PROFESSIONAL_TYPE_CODES.get(professional_type, ("other", "Other"))
    quals.append(
        PractitionerQualification(
            code=CodeableConcept(
                coding=[
                    Coding(
                        system="http://africare.app/fhir/professional-type",
                        code=type_code,
                        display=type_display,
                    )
                ]
            )
        )
    )

    # Sub-specialty if provided
    if sub_specialty:
        quals.append(
            PractitionerQualification(
                code=CodeableConcept(
                    coding=[
                        Coding(
                            system="http://africare.app/fhir/sub-specialty",
                            code=sub_specialty.lower().replace(" ", "-"),
                            display=sub_specialty,
                        )
                    ]
                )
            )
        )

    # Free-text qualifications
    if qualifications:
        quals.append(
            PractitionerQualification(
                code=CodeableConcept(
                    coding=[
                        Coding(
                            system="http://africare.app/fhir/qualifications",
                            display=qualifications,
                        )
                    ]
                )
            )
        )

    return quals


def _build_facility_extension(
    facility_name: str | None,
    facility_type: str | None,
    facility_address: str | None,
    facility_city: str | None,
    facility_region: str | None,
) -> Extension | None:
    """Build FHIR extension for facility information."""
    if not any([facility_name, facility_type, facility_address, facility_city, facility_region]):
        return None

    sub_extensions = []

    if facility_name:
        sub_extensions.append(Extension(url="name", valueString=facility_name))
    if facility_type:
        sub_extensions.append(Extension(url="type", valueString=facility_type))
    if facility_address:
        sub_extensions.append(Extension(url="address", valueString=facility_address))
    if facility_city:
        sub_extensions.append(Extension(url="city", valueString=facility_city))
    if facility_region:
        sub_extensions.append(Extension(url="region", valueString=facility_region))

    return Extension(url=FACILITY_EXTENSION_URL, extension=sub_extensions)


def _build_experience_extension(years: int | None) -> Extension | None:
    """Build FHIR extension for years of experience."""
    if years is None:
        return None

    return Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=years)


def _build_communication(languages_spoken: str) -> list[PractitionerCommunication]:
    """Build FHIR communication for spoken languages."""
    languages = languages_spoken.split(",") if languages_spoken else ["fr"]
    return [
        PractitionerCommunication(
            language=CodeableConcept(
                coding=[
                    Coding(
                        system="urn:ietf:bcp:47",
                        code=lang.strip(),
                    )
                ]
            )
        )
        for lang in languages
        if lang.strip()
    ]


# =============================================================================
# Helper functions for applying updates to FHIR Practitioner
# =============================================================================


def _apply_name_updates(practitioner: FHIRPractitioner, updates: ProfessionalUpdate) -> None:
    """Apply name updates to FHIR Practitioner."""
    if updates.first_name is None and updates.last_name is None and updates.title is None:
        return

    current_name = practitioner.name[0] if practitioner.name else HumanName(use="official")

    first_name = updates.first_name or (current_name.given[0] if current_name.given else "")
    last_name = updates.last_name or current_name.family or ""
    title = updates.title or "Dr"

    practitioner.name = _build_name(first_name, last_name, title)


def _apply_telecom_updates(practitioner: FHIRPractitioner, updates: ProfessionalUpdate) -> None:
    """Apply telecom updates to FHIR Practitioner."""
    if updates.email is None and updates.phone is None and updates.phone_secondary is None:
        return

    current = _extract_telecom(practitioner)
    email = updates.email or current["email"] or ""
    phone = updates.phone or current["phone"] or ""
    phone_secondary = (
        updates.phone_secondary
        if updates.phone_secondary is not None
        else current["phone_secondary"]
    )

    practitioner.telecom = _build_telecom(email, phone, phone_secondary)


def _apply_qualification_updates(
    practitioner: FHIRPractitioner, updates: ProfessionalUpdate
) -> None:
    """Apply qualification updates to FHIR Practitioner."""
    if (
        updates.specialty is None
        and updates.professional_type is None
        and updates.sub_specialty is None
        and updates.qualifications is None
    ):
        return

    current = _extract_qualification(practitioner)
    specialty = updates.specialty or current["specialty"]
    professional_type = updates.professional_type or current["professional_type"]
    sub_specialty = (
        updates.sub_specialty if updates.sub_specialty is not None else current["sub_specialty"]
    )
    qualifications = (
        updates.qualifications if updates.qualifications is not None else current["qualifications"]
    )

    practitioner.qualification = _build_qualifications(
        specialty, professional_type, sub_specialty, qualifications
    )


def _apply_facility_updates(practitioner: FHIRPractitioner, updates: ProfessionalUpdate) -> None:
    """Apply facility updates to FHIR Practitioner."""
    if (
        updates.facility_name is None
        and updates.facility_type is None
        and updates.facility_address is None
        and updates.facility_city is None
        and updates.facility_region is None
    ):
        return

    current = _extract_facility(practitioner)
    facility_ext = _build_facility_extension(
        updates.facility_name if updates.facility_name is not None else current["facility_name"],
        updates.facility_type if updates.facility_type is not None else current["facility_type"],
        updates.facility_address
        if updates.facility_address is not None
        else current["facility_address"],
        updates.facility_city if updates.facility_city is not None else current["facility_city"],
        updates.facility_region
        if updates.facility_region is not None
        else current["facility_region"],
    )

    # Remove existing facility extension and add new one
    if practitioner.extension:
        practitioner.extension = [
            ext for ext in practitioner.extension if ext.url != FACILITY_EXTENSION_URL
        ]
    else:
        practitioner.extension = []

    if facility_ext:
        practitioner.extension.append(facility_ext)


def _apply_experience_updates(practitioner: FHIRPractitioner, updates: ProfessionalUpdate) -> None:
    """Apply experience updates to FHIR Practitioner."""
    if updates.years_of_experience is None:
        return

    exp_ext = _build_experience_extension(updates.years_of_experience)

    # Remove existing experience extension and add new one
    if practitioner.extension:
        practitioner.extension = [
            ext for ext in practitioner.extension if ext.url != EXPERIENCE_EXTENSION_URL
        ]
    else:
        practitioner.extension = []

    if exp_ext:
        practitioner.extension.append(exp_ext)


def _apply_language_updates(practitioner: FHIRPractitioner, updates: ProfessionalUpdate) -> None:
    """Apply language updates to FHIR Practitioner."""
    if updates.languages_spoken is None:
        return

    practitioner.communication = _build_communication(updates.languages_spoken)


# =============================================================================
# Main Mapper Class
# =============================================================================


class ProfessionalMapper:
    """Mapper bidirectionnel entre Professional Pydantic et FHIR Practitioner."""

    @staticmethod
    def to_fhir(professional: ProfessionalCreate) -> FHIRPractitioner:
        """Convertit un schema ProfessionalCreate en ressource FHIR Practitioner.

        Args:
            professional: Schema Pydantic de creation

        Returns:
            Ressource FHIR Practitioner prete pour envoi au serveur
        """
        extensions = []

        # Facility extension
        facility_ext = _build_facility_extension(
            professional.facility_name,
            professional.facility_type,
            professional.facility_address,
            professional.facility_city,
            professional.facility_region,
        )
        if facility_ext:
            extensions.append(facility_ext)

        # Experience extension
        exp_ext = _build_experience_extension(professional.years_of_experience)
        if exp_ext:
            extensions.append(exp_ext)

        practitioner_data = {
            "resourceType": "Practitioner",
            "identifier": _build_identifiers(
                professional.keycloak_user_id, professional.professional_id
            ),
            "active": True,
            "name": _build_name(
                professional.first_name, professional.last_name, professional.title
            ),
            "telecom": _build_telecom(
                professional.email, professional.phone, professional.phone_secondary
            ),
            "qualification": _build_qualifications(
                professional.specialty,
                professional.professional_type,
                professional.sub_specialty,
                professional.qualifications,
            ),
            "communication": _build_communication(professional.languages_spoken),
        }

        if extensions:
            practitioner_data["extension"] = extensions

        return FHIRPractitioner(**practitioner_data)

    @staticmethod
    def from_fhir(
        practitioner: FHIRPractitioner,
        local_id: int,
        gdpr_metadata: dict | None = None,
    ) -> ProfessionalResponse:
        """Convertit une ressource FHIR Practitioner en ProfessionalResponse.

        Args:
            practitioner: Ressource FHIR Practitioner
            local_id: ID numerique local (depuis table GDPR)
            gdpr_metadata: Metadonnees GDPR locales optionnelles

        Returns:
            Schema Pydantic ProfessionalResponse
        """
        gdpr = gdpr_metadata or {}

        # Extract all components
        identifiers = _extract_identifiers(practitioner)
        name = _extract_name(practitioner)
        telecom = _extract_telecom(practitioner)
        qualification = _extract_qualification(practitioner)
        facility = _extract_facility(practitioner)
        experience = _extract_experience(practitioner)
        languages = _extract_languages(practitioner)

        return ProfessionalResponse(
            id=local_id,
            keycloak_user_id=identifiers["keycloak_user_id"] or "",
            professional_id=identifiers["professional_id"],
            first_name=name["first_name"],
            last_name=name["last_name"],
            title=name["title"],
            email=telecom["email"] or "",
            phone=telecom["phone"] or "",
            phone_secondary=telecom["phone_secondary"],
            specialty=qualification["specialty"],
            sub_specialty=qualification["sub_specialty"],
            professional_type=qualification["professional_type"],
            qualifications=qualification["qualifications"],
            facility_name=facility["facility_name"],
            facility_type=facility["facility_type"],
            facility_address=facility["facility_address"],
            facility_city=facility["facility_city"],
            facility_region=facility["facility_region"],
            years_of_experience=experience,
            languages_spoken=languages,
            is_active=practitioner.active if practitioner.active is not None else True,
            is_verified=gdpr.get("is_verified", False),
            is_available=gdpr.get("is_available", True),
            digital_signature=gdpr.get("digital_signature"),
            notes=gdpr.get("notes"),
            created_at=gdpr.get("created_at", datetime.now()),
            updated_at=gdpr.get("updated_at", datetime.now()),
            created_by=gdpr.get("created_by"),
            updated_by=gdpr.get("updated_by"),
        )

    @staticmethod
    def to_list_item(
        practitioner: FHIRPractitioner,
        local_id: int,
        gdpr_metadata: dict | None = None,
    ) -> ProfessionalListItem:
        """Convertit une ressource FHIR Practitioner en ProfessionalListItem.

        Args:
            practitioner: Ressource FHIR Practitioner
            local_id: ID numerique local
            gdpr_metadata: Metadonnees GDPR locales optionnelles

        Returns:
            Schema Pydantic ProfessionalListItem optimise pour listes
        """
        gdpr = gdpr_metadata or {}

        name = _extract_name(practitioner)
        telecom = _extract_telecom(practitioner)
        qualification = _extract_qualification(practitioner)
        facility = _extract_facility(practitioner)

        return ProfessionalListItem(
            id=local_id,
            title=name["title"],
            first_name=name["first_name"],
            last_name=name["last_name"],
            specialty=qualification["specialty"],
            professional_type=qualification["professional_type"],
            email=telecom["email"] or "",
            phone=telecom["phone"] or "",
            facility_name=facility["facility_name"],
            is_active=practitioner.active if practitioner.active is not None else True,
            is_verified=gdpr.get("is_verified", False),
            is_available=gdpr.get("is_available", True),
            created_at=gdpr.get("created_at", datetime.now()),
        )

    @staticmethod
    def apply_updates(
        practitioner: FHIRPractitioner, updates: ProfessionalUpdate
    ) -> FHIRPractitioner:
        """Applique les mises a jour partielles a une ressource FHIR Practitioner.

        Args:
            practitioner: Ressource FHIR existante
            updates: Schema de mise a jour partielle

        Returns:
            Ressource FHIR mise a jour
        """
        # Apply name updates
        _apply_name_updates(practitioner, updates)

        # Apply telecom updates
        _apply_telecom_updates(practitioner, updates)

        # Apply qualification updates
        _apply_qualification_updates(practitioner, updates)

        # Apply facility updates
        _apply_facility_updates(practitioner, updates)

        # Apply experience updates
        _apply_experience_updates(practitioner, updates)

        # Apply language updates
        _apply_language_updates(practitioner, updates)

        # Apply active status
        if updates.is_active is not None:
            practitioner.active = updates.is_active

        return practitioner
