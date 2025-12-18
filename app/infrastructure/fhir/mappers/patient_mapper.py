"""Bidirectional mapper between Pydantic Patient schemas and FHIR Patient resource.

This module handles the conversion between the AfriCare Patient schemas and
FHIR R4 Patient resources for communication with HAPI FHIR server.
"""

from datetime import date, datetime
from typing import Any, Literal

from fhir.resources.address import Address as FHIRAddress
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.extension import Extension
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.patient import Patient as FHIRPatient
from fhir.resources.patient import PatientCommunication, PatientContact

from app.infrastructure.fhir.identifiers import (
    GPS_EXTENSION_URL,
    KEYCLOAK_SYSTEM,
    NATIONAL_ID_SYSTEM,
)
from app.schemas.patient import (
    PatientCreate,
    PatientListItem,
    PatientResponse,
    PatientUpdate,
)

# Helper functions for FHIR data extraction (reduce complexity in main methods)


def _extract_identifiers(fhir_patient: FHIRPatient) -> tuple[str | None, str | None]:
    """Extract keycloak_user_id and national_id from FHIR Patient identifiers."""
    keycloak_user_id: str | None = None
    national_id: str | None = None
    for identifier in fhir_patient.identifier or []:
        if identifier.system == KEYCLOAK_SYSTEM:
            keycloak_user_id = identifier.value
        elif identifier.system == NATIONAL_ID_SYSTEM:
            national_id = identifier.value
    return keycloak_user_id, national_id


def _extract_name(fhir_patient: FHIRPatient) -> tuple[str, str]:
    """Extract first_name and last_name from FHIR Patient name."""
    first_name = ""
    last_name = ""
    if fhir_patient.name:
        name = fhir_patient.name[0]
        last_name = name.family or ""
        first_name = name.given[0] if name.given else ""
    return first_name, last_name


def _extract_telecom(fhir_patient: FHIRPatient) -> tuple[str | None, str | None, str | None]:
    """Extract email, phone, and phone_secondary from FHIR Patient telecom."""
    email: str | None = None
    phone: str | None = None
    phone_secondary: str | None = None
    for contact_point in fhir_patient.telecom or []:
        if contact_point.system == "email":
            email = contact_point.value
        elif contact_point.system == "phone":
            if contact_point.use == "mobile" or phone is None:
                if phone is None:
                    phone = contact_point.value
                elif phone_secondary is None:
                    phone_secondary = contact_point.value
    return email, phone, phone_secondary


def _extract_address(
    fhir_patient: FHIRPatient,
) -> tuple[str | None, str | None, str | None, str | None, str | None, str]:
    """Extract address fields from FHIR Patient address."""
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str = "Senegal"
    if fhir_patient.address:
        addr = fhir_patient.address[0]
        if addr.line:
            address_line1 = addr.line[0] if len(addr.line) > 0 else None
            address_line2 = addr.line[1] if len(addr.line) > 1 else None
        city = addr.city
        region = addr.state
        postal_code = addr.postalCode
        country = addr.country or "Senegal"
    return address_line1, address_line2, city, region, postal_code, country


def _extract_gps(fhir_patient: FHIRPatient) -> tuple[float | None, float | None]:
    """Extract GPS coordinates from FHIR Patient extensions."""
    latitude: float | None = None
    longitude: float | None = None
    for ext in fhir_patient.extension or []:
        if ext.url == GPS_EXTENSION_URL:
            for sub_ext in ext.extension or []:
                if sub_ext.url == "latitude" and sub_ext.valueDecimal is not None:
                    latitude = float(sub_ext.valueDecimal)
                elif sub_ext.url == "longitude" and sub_ext.valueDecimal is not None:
                    longitude = float(sub_ext.valueDecimal)
    return latitude, longitude


def _extract_emergency_contact(fhir_patient: FHIRPatient) -> tuple[str | None, str | None]:
    """Extract emergency contact from FHIR Patient contact."""
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    if fhir_patient.contact:
        contact = fhir_patient.contact[0]
        if contact.name and contact.name.text:
            emergency_contact_name = contact.name.text
        if contact.telecom:
            emergency_contact_phone = contact.telecom[0].value
    return emergency_contact_name, emergency_contact_phone


def _extract_preferred_language(fhir_patient: FHIRPatient) -> Literal["fr", "en"]:
    """Extract preferred language from FHIR Patient communication."""
    preferred_language: Literal["fr", "en"] = "fr"
    if fhir_patient.communication:
        comm = fhir_patient.communication[0]
        if comm.language and comm.language.coding:
            lang_code = comm.language.coding[0].code
            if lang_code in ("fr", "en"):
                preferred_language = lang_code  # type: ignore[assignment]
    return preferred_language


def _extract_birth_date(fhir_patient: FHIRPatient) -> date:
    """Extract birth date from FHIR Patient."""
    if fhir_patient.birthDate:
        if isinstance(fhir_patient.birthDate, str):
            return date.fromisoformat(fhir_patient.birthDate)
        return fhir_patient.birthDate
    return date(1900, 1, 1)


class PatientMapper:
    """Maps between Pydantic Patient schemas and FHIR Patient resource.

    This mapper handles:
    - PatientCreate -> FHIR Patient (to_fhir)
    - FHIR Patient -> PatientResponse (from_fhir)
    - PatientUpdate application to existing FHIR Patient (apply_updates)
    """

    @staticmethod
    def to_fhir(
        schema: PatientCreate,
        fhir_id: str | None = None,
    ) -> FHIRPatient:
        """Convert Pydantic PatientCreate to FHIR Patient.

        Args:
            schema: Pydantic patient creation schema
            fhir_id: Optional FHIR resource ID (for updates)

        Returns:
            FHIR Patient resource ready for server submission
        """
        # Build identifiers
        identifiers = [
            Identifier(
                system=KEYCLOAK_SYSTEM,
                value=schema.keycloak_user_id,
                use="official",
            )
        ]
        if schema.national_id:
            identifiers.append(
                Identifier(
                    system=NATIONAL_ID_SYSTEM,
                    value=schema.national_id,
                    use="official",
                )
            )

        # Build name
        name = HumanName(
            use="official",
            family=schema.last_name,
            given=[schema.first_name],
        )

        # Build telecom (contact points)
        telecom = _build_telecom(schema.email, schema.phone, schema.phone_secondary)

        # Build address
        address = _build_address(schema)

        # Build extensions (GPS coordinates)
        extensions = _build_gps_extension(schema.latitude, schema.longitude)

        # Build emergency contact
        contact = _build_emergency_contact(
            schema.emergency_contact_name, schema.emergency_contact_phone
        )

        # Build communication (preferred language)
        communication = _build_communication(schema.preferred_language)

        # Build FHIR Patient
        patient_data: dict[str, Any] = {
            "resourceType": "Patient",
            "identifier": identifiers,
            "active": True,
            "name": [name],
            "telecom": telecom if telecom else None,
            "gender": schema.gender,
            "birthDate": schema.date_of_birth.isoformat(),
            "address": [address] if address else None,
            "contact": [contact] if contact else None,
            "communication": [communication],
            "extension": extensions if extensions else None,
        }

        if fhir_id:
            patient_data["id"] = fhir_id

        return FHIRPatient.model_validate(patient_data)

    @staticmethod
    def from_fhir(
        fhir_patient: FHIRPatient,
        local_id: int,
        gdpr_metadata: dict[str, Any],
    ) -> PatientResponse:
        """Convert FHIR Patient to Pydantic PatientResponse.

        Args:
            fhir_patient: FHIR Patient resource from server
            local_id: Local database ID (for API retrocompatibility)
            gdpr_metadata: Local GDPR metadata dict

        Returns:
            PatientResponse schema for API response
        """
        keycloak_user_id, national_id = _extract_identifiers(fhir_patient)
        first_name, last_name = _extract_name(fhir_patient)
        email, phone, phone_secondary = _extract_telecom(fhir_patient)
        address_line1, address_line2, city, region, postal_code, country = _extract_address(
            fhir_patient
        )
        latitude, longitude = _extract_gps(fhir_patient)
        emergency_contact_name, emergency_contact_phone = _extract_emergency_contact(fhir_patient)
        preferred_language = _extract_preferred_language(fhir_patient)
        birth_date = _extract_birth_date(fhir_patient)

        return PatientResponse(
            id=local_id,
            keycloak_user_id=keycloak_user_id or "",
            national_id=national_id,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=birth_date,
            gender=fhir_patient.gender or "male",
            email=email,
            phone=phone,
            phone_secondary=phone_secondary,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            region=region,
            postal_code=postal_code,
            country=country,
            latitude=latitude,
            longitude=longitude,
            emergency_contact_name=emergency_contact_name,
            emergency_contact_phone=emergency_contact_phone,
            preferred_language=preferred_language,
            is_active=fhir_patient.active if fhir_patient.active is not None else True,
            is_verified=gdpr_metadata.get("is_verified", False),
            notes=gdpr_metadata.get("notes"),
            created_at=gdpr_metadata.get("created_at", datetime.now()),
            updated_at=gdpr_metadata.get("updated_at", datetime.now()),
            created_by=gdpr_metadata.get("created_by"),
            updated_by=gdpr_metadata.get("updated_by"),
        )

    @staticmethod
    def to_list_item(
        fhir_patient: FHIRPatient,
        local_id: int,
        gdpr_metadata: dict[str, Any],
    ) -> PatientListItem:
        """Convert FHIR Patient to PatientListItem for list responses."""
        first_name, last_name = _extract_name(fhir_patient)
        email, phone, _ = _extract_telecom(fhir_patient)
        birth_date = _extract_birth_date(fhir_patient)

        return PatientListItem(
            id=local_id,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=birth_date,
            gender=fhir_patient.gender or "male",
            phone=phone,
            email=email,
            is_active=fhir_patient.active if fhir_patient.active is not None else True,
            is_verified=gdpr_metadata.get("is_verified", False),
            created_at=gdpr_metadata.get("created_at", datetime.now()),
        )

    @staticmethod
    def apply_updates(
        fhir_patient: FHIRPatient,
        updates: PatientUpdate,
    ) -> FHIRPatient:
        """Apply PatientUpdate to an existing FHIR Patient.

        Args:
            fhir_patient: Existing FHIR Patient resource
            updates: Pydantic PatientUpdate with fields to change

        Returns:
            Updated FHIR Patient resource
        """
        update_data = updates.model_dump(exclude_unset=True)

        _apply_name_updates(fhir_patient, update_data)
        _apply_basic_updates(fhir_patient, update_data)
        _apply_telecom_updates(fhir_patient, update_data)
        _apply_address_updates(fhir_patient, update_data)
        _apply_gps_updates(fhir_patient, update_data)
        _apply_emergency_contact_updates(fhir_patient, update_data)
        _apply_language_updates(fhir_patient, update_data)

        return fhir_patient


# Helper functions for building FHIR components


def _build_telecom(
    email: str | None, phone: str | None, phone_secondary: str | None
) -> list[ContactPoint]:
    """Build telecom list from contact information."""
    telecom: list[ContactPoint] = []
    if email:
        telecom.append(ContactPoint(system="email", value=email, use="home"))
    if phone:
        telecom.append(ContactPoint(system="phone", value=phone, use="mobile", rank=1))
    if phone_secondary:
        telecom.append(ContactPoint(system="phone", value=phone_secondary, use="home", rank=2))
    return telecom


def _build_address(schema: PatientCreate) -> FHIRAddress | None:
    """Build FHIR Address from schema."""
    if not any([schema.address_line1, schema.city, schema.region, schema.country]):
        return None
    lines = [ln for ln in [schema.address_line1, schema.address_line2] if ln]
    return FHIRAddress(
        use="home",
        type="physical",
        line=lines if lines else None,
        city=schema.city,
        state=schema.region,
        postalCode=schema.postal_code,
        country=schema.country,
    )


def _build_gps_extension(latitude: float | None, longitude: float | None) -> list[Extension]:
    """Build GPS extension list."""
    extensions: list[Extension] = []
    if latitude is not None and longitude is not None:
        extensions.append(
            Extension(
                url=GPS_EXTENSION_URL,
                extension=[
                    Extension(url="latitude", valueDecimal=latitude),
                    Extension(url="longitude", valueDecimal=longitude),
                ],
            )
        )
    return extensions


def _build_emergency_contact(name: str | None, phone: str | None) -> PatientContact | None:
    """Build emergency contact from name and phone."""
    if not name and not phone:
        return None
    contact_telecom: list[ContactPoint] = []
    if phone:
        contact_telecom.append(ContactPoint(system="phone", value=phone, use="home"))
    return PatientContact(
        relationship=[
            CodeableConcept(
                coding=[
                    Coding(
                        system="http://terminology.hl7.org/CodeSystem/v2-0131",
                        code="C",
                        display="Emergency Contact",
                    )
                ]
            )
        ],
        name=HumanName(text=name) if name else None,
        telecom=contact_telecom if contact_telecom else None,
    )


def _build_communication(preferred_language: str) -> PatientCommunication:
    """Build communication with preferred language."""
    return PatientCommunication(
        language=CodeableConcept(
            coding=[
                Coding(
                    system="urn:ietf:bcp:47",
                    code=preferred_language,
                    display="Francais" if preferred_language == "fr" else "English",
                )
            ]
        ),
        preferred=True,
    )


# Helper functions for applying updates


def _apply_name_updates(fhir_patient: FHIRPatient, update_data: dict[str, Any]) -> None:
    """Apply name updates to FHIR Patient."""
    if "first_name" in update_data or "last_name" in update_data:
        if fhir_patient.name:
            name = fhir_patient.name[0]
            if "first_name" in update_data:
                name.given = [update_data["first_name"]]
            if "last_name" in update_data:
                name.family = update_data["last_name"]


def _apply_basic_updates(fhir_patient: FHIRPatient, update_data: dict[str, Any]) -> None:
    """Apply gender, birth date, and is_active updates."""
    if "gender" in update_data:
        fhir_patient.gender = update_data["gender"]
    if "date_of_birth" in update_data:
        fhir_patient.birthDate = update_data["date_of_birth"].isoformat()
    if "is_active" in update_data:
        fhir_patient.active = update_data["is_active"]


def _apply_telecom_updates(fhir_patient: FHIRPatient, update_data: dict[str, Any]) -> None:
    """Apply telecom (email, phone) updates."""
    if not any(k in update_data for k in ["email", "phone", "phone_secondary"]):
        return

    email = update_data.get("email")
    phone = update_data.get("phone")
    phone_secondary = update_data.get("phone_secondary")

    # Get existing values if not in update
    for cp in fhir_patient.telecom or []:
        if cp.system == "email" and "email" not in update_data:
            email = cp.value
        elif cp.system == "phone":
            if cp.use == "mobile" and "phone" not in update_data:
                phone = cp.value
            elif cp.use == "home" and "phone_secondary" not in update_data:
                phone_secondary = cp.value

    fhir_patient.telecom = _build_telecom(email, phone, phone_secondary) or None


def _apply_address_updates(fhir_patient: FHIRPatient, update_data: dict[str, Any]) -> None:
    """Apply address updates."""
    address_fields = ["address_line1", "address_line2", "city", "region", "postal_code", "country"]
    if not any(k in update_data for k in address_fields):
        return

    existing_addr = fhir_patient.address[0] if fhir_patient.address else None
    lines = _get_updated_address_lines(update_data, existing_addr)

    new_addr = FHIRAddress(
        use="home",
        type="physical",
        line=lines if lines else None,
        city=update_data.get("city", existing_addr.city if existing_addr else None),
        state=update_data.get("region", existing_addr.state if existing_addr else None),
        postalCode=update_data.get(
            "postal_code", existing_addr.postalCode if existing_addr else None
        ),
        country=update_data.get("country", existing_addr.country if existing_addr else "Senegal"),
    )
    fhir_patient.address = [new_addr]


def _get_updated_address_lines(
    update_data: dict[str, Any], existing_addr: FHIRAddress | None
) -> list[str]:
    """Get updated address lines, preserving existing if not updated."""
    lines: list[str] = []
    if "address_line1" in update_data:
        if update_data["address_line1"]:
            lines.append(update_data["address_line1"])
    elif existing_addr and existing_addr.line and len(existing_addr.line) > 0:
        lines.append(existing_addr.line[0])

    if "address_line2" in update_data:
        if update_data["address_line2"]:
            lines.append(update_data["address_line2"])
    elif existing_addr and existing_addr.line and len(existing_addr.line) > 1:
        lines.append(existing_addr.line[1])

    return lines


def _apply_gps_updates(fhir_patient: FHIRPatient, update_data: dict[str, Any]) -> None:
    """Apply GPS coordinate updates."""
    if "latitude" not in update_data and "longitude" not in update_data:
        return

    lat = update_data.get("latitude")
    lon = update_data.get("longitude")

    # Preserve existing if not updated
    for ext in fhir_patient.extension or []:
        if ext.url == GPS_EXTENSION_URL:
            for sub_ext in ext.extension or []:
                if sub_ext.url == "latitude" and "latitude" not in update_data:
                    lat = float(sub_ext.valueDecimal) if sub_ext.valueDecimal else None
                elif sub_ext.url == "longitude" and "longitude" not in update_data:
                    lon = float(sub_ext.valueDecimal) if sub_ext.valueDecimal else None

    # Remove old GPS extension
    extensions = [e for e in (fhir_patient.extension or []) if e.url != GPS_EXTENSION_URL]

    # Add updated GPS extension if both values present
    if lat is not None and lon is not None:
        extensions.extend(_build_gps_extension(lat, lon))

    fhir_patient.extension = extensions if extensions else None


def _apply_emergency_contact_updates(
    fhir_patient: FHIRPatient, update_data: dict[str, Any]
) -> None:
    """Apply emergency contact updates."""
    if "emergency_contact_name" not in update_data and "emergency_contact_phone" not in update_data:
        return

    existing_contact = fhir_patient.contact[0] if fhir_patient.contact else None

    name = update_data.get("emergency_contact_name")
    phone = update_data.get("emergency_contact_phone")

    # Preserve existing if not updated
    if existing_contact:
        if "emergency_contact_name" not in update_data and existing_contact.name:
            name = existing_contact.name.text
        if "emergency_contact_phone" not in update_data and existing_contact.telecom:
            phone = existing_contact.telecom[0].value

    contact = _build_emergency_contact(name, phone)
    fhir_patient.contact = [contact] if contact else None


def _apply_language_updates(fhir_patient: FHIRPatient, update_data: dict[str, Any]) -> None:
    """Apply preferred language update."""
    if "preferred_language" in update_data:
        fhir_patient.communication = [_build_communication(update_data["preferred_language"])]
