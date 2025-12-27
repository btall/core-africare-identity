"""Tests unitaires pour le mapper Professional <-> FHIR Practitioner.

Ce module teste toutes les fonctions de conversion entre les schemas Pydantic
Professional et les ressources FHIR R4 Practitioner.
"""

from datetime import UTC, datetime

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
from app.infrastructure.fhir.mappers.professional_mapper import (
    EXPERIENCE_EXTENSION_URL,
    FACILITY_EXTENSION_URL,
    ProfessionalMapper,
    _apply_experience_updates,
    _apply_facility_updates,
    _apply_language_updates,
    _apply_name_updates,
    _apply_qualification_updates,
    _apply_telecom_updates,
    _build_communication,
    _build_experience_extension,
    _build_facility_extension,
    _build_identifiers,
    _build_name,
    _build_qualifications,
    _build_telecom,
    _extract_experience,
    _extract_facility,
    _extract_facility_sub_extensions,
    _extract_identifiers,
    _extract_languages,
    _extract_name,
    _extract_qualification,
    _extract_telecom,
)
from app.schemas.professional import (
    ProfessionalCreate,
    ProfessionalUpdate,
)

# =============================================================================
# Tests for helper extraction functions
# =============================================================================


class TestExtractIdentifiers:
    """Tests pour _extract_identifiers()."""

    def test_extract_both_identifiers(self):
        """Test extraction avec keycloak et professional_id."""
        practitioner = FHIRPractitioner(
            identifier=[
                Identifier(system=KEYCLOAK_SYSTEM, value="keycloak-uuid-123"),
                Identifier(system=PROFESSIONAL_LICENSE_SYSTEM, value="CNOM-12345"),
            ]
        )

        result = _extract_identifiers(practitioner)

        assert result["keycloak_user_id"] == "keycloak-uuid-123"
        assert result["professional_id"] == "CNOM-12345"

    def test_extract_keycloak_only(self):
        """Test extraction avec keycloak uniquement."""
        practitioner = FHIRPractitioner(
            identifier=[
                Identifier(system=KEYCLOAK_SYSTEM, value="keycloak-only-456"),
            ]
        )

        result = _extract_identifiers(practitioner)

        assert result["keycloak_user_id"] == "keycloak-only-456"
        assert result["professional_id"] is None

    def test_extract_no_identifiers(self):
        """Test extraction sans identifiants."""
        practitioner = FHIRPractitioner(identifier=None)

        result = _extract_identifiers(practitioner)

        assert result["keycloak_user_id"] is None
        assert result["professional_id"] is None

    def test_extract_other_system_identifiers(self):
        """Test extraction avec autres systemes ignores."""
        practitioner = FHIRPractitioner(
            identifier=[
                Identifier(system="http://other.system/id", value="other-value"),
                Identifier(system=KEYCLOAK_SYSTEM, value="keycloak-789"),
            ]
        )

        result = _extract_identifiers(practitioner)

        assert result["keycloak_user_id"] == "keycloak-789"
        assert result["professional_id"] is None


class TestExtractName:
    """Tests pour _extract_name()."""

    def test_extract_full_name_with_prefix(self):
        """Test extraction nom complet avec prefix Dr."""
        practitioner = FHIRPractitioner(
            name=[
                HumanName(
                    use="official",
                    family="Diallo",
                    given=["Amadou"],
                    prefix=["Dr."],
                )
            ]
        )

        result = _extract_name(practitioner)

        assert result["first_name"] == "Amadou"
        assert result["last_name"] == "Diallo"
        assert result["title"] == "Dr"

    def test_extract_name_with_prof_prefix(self):
        """Test extraction nom avec prefix Professeur."""
        practitioner = FHIRPractitioner(
            name=[
                HumanName(
                    family="Ndiaye",
                    given=["Fatou"],
                    prefix=["Prof."],
                )
            ]
        )

        result = _extract_name(practitioner)

        assert result["first_name"] == "Fatou"
        assert result["last_name"] == "Ndiaye"
        assert result["title"] == "Pr"

    def test_extract_name_family_only(self):
        """Test extraction avec nom de famille uniquement."""
        practitioner = FHIRPractitioner(name=[HumanName(family="Sow")])

        result = _extract_name(practitioner)

        assert result["first_name"] == ""
        assert result["last_name"] == "Sow"
        assert result["title"] == "Dr"  # Default

    def test_extract_no_name(self):
        """Test extraction sans nom."""
        practitioner = FHIRPractitioner(name=None)

        result = _extract_name(practitioner)

        assert result["first_name"] == ""
        assert result["last_name"] == ""
        assert result["title"] == "Dr"

    def test_extract_name_empty_list(self):
        """Test extraction avec liste vide."""
        practitioner = FHIRPractitioner(name=[])

        result = _extract_name(practitioner)

        assert result["first_name"] == ""
        assert result["last_name"] == ""
        assert result["title"] == "Dr"

    def test_extract_name_multiple_given(self):
        """Test extraction avec plusieurs prenoms."""
        practitioner = FHIRPractitioner(
            name=[
                HumanName(
                    family="Ba",
                    given=["Moussa", "Ibrahima"],
                )
            ]
        )

        result = _extract_name(practitioner)

        assert result["first_name"] == "Moussa"  # Premier prenom seulement
        assert result["last_name"] == "Ba"


class TestExtractTelecom:
    """Tests pour _extract_telecom()."""

    def test_extract_all_telecom(self):
        """Test extraction de tous les contacts.

        NOTE: L'ordre des ContactPoint phone determine phone vs phone_secondary.
        Le premier phone devient phone, le second devient phone_secondary.
        """
        practitioner = FHIRPractitioner(
            telecom=[
                ContactPoint(system="email", value="dr.diallo@africare.sn"),
                ContactPoint(system="phone", value="+221771234567"),
                ContactPoint(system="phone", value="+221339876543"),
            ]
        )

        result = _extract_telecom(practitioner)

        assert result["email"] == "dr.diallo@africare.sn"
        assert result["phone"] == "+221771234567"
        assert result["phone_secondary"] == "+221339876543"

    def test_extract_email_only(self):
        """Test extraction email uniquement."""
        practitioner = FHIRPractitioner(
            telecom=[
                ContactPoint(system="email", value="nurse@hospital.sn"),
            ]
        )

        result = _extract_telecom(practitioner)

        assert result["email"] == "nurse@hospital.sn"
        assert result["phone"] is None
        assert result["phone_secondary"] is None

    def test_extract_no_telecom(self):
        """Test extraction sans telecom."""
        practitioner = FHIRPractitioner(telecom=None)

        result = _extract_telecom(practitioner)

        assert result["email"] is None
        assert result["phone"] is None
        assert result["phone_secondary"] is None


class TestExtractQualification:
    """Tests pour _extract_qualification()."""

    def test_extract_full_qualification(self):
        """Test extraction qualification complete."""
        practitioner = FHIRPractitioner(
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                code="cardiology",
                                display="Cardiologie",
                            )
                        ]
                    )
                ),
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/professional-type",
                                code="physician",
                                display="Physician",
                            )
                        ]
                    )
                ),
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/sub-specialty",
                                code="interventional",
                                display="Cardiologie Interventionnelle",
                            )
                        ]
                    )
                ),
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/qualifications",
                                display="MD, PhD, FACC",
                            )
                        ]
                    )
                ),
            ]
        )

        result = _extract_qualification(practitioner)

        assert result["specialty"] == "Cardiologie"
        assert result["professional_type"] == "physician"
        assert result["sub_specialty"] == "Cardiologie Interventionnelle"
        assert result["qualifications"] == "MD, PhD, FACC"

    def test_extract_minimal_qualification(self):
        """Test extraction qualification minimale."""
        practitioner = FHIRPractitioner(
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="Medecine Generale",
                            )
                        ]
                    )
                ),
            ]
        )

        result = _extract_qualification(practitioner)

        assert result["specialty"] == "Medecine Generale"
        assert result["professional_type"] == "other"  # Default
        assert result["sub_specialty"] is None
        assert result["qualifications"] is None

    def test_extract_no_qualification(self):
        """Test extraction sans qualification."""
        practitioner = FHIRPractitioner(qualification=None)

        result = _extract_qualification(practitioner)

        assert result["specialty"] == ""
        assert result["professional_type"] == "other"
        assert result["sub_specialty"] is None
        assert result["qualifications"] is None

    def test_extract_qualification_nurse_type(self):
        """Test extraction type infirmier."""
        practitioner = FHIRPractitioner(
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/professional-type",
                                code="nurse",
                            )
                        ]
                    )
                ),
            ]
        )

        result = _extract_qualification(practitioner)

        assert result["professional_type"] == "nurse"


class TestExtractFacilitySubExtensions:
    """Tests pour _extract_facility_sub_extensions()."""

    def test_extract_all_facility_fields(self):
        """Test extraction de tous les champs facility."""
        sub_extensions = [
            Extension(url="name", valueString="Hopital Principal de Dakar"),
            Extension(url="type", valueString="hospital"),
            Extension(url="address", valueString="1 Avenue Nelson Mandela"),
            Extension(url="city", valueString="Dakar"),
            Extension(url="region", valueString="Dakar"),
        ]

        result = _extract_facility_sub_extensions(sub_extensions)

        assert result["facility_name"] == "Hopital Principal de Dakar"
        assert result["facility_type"] == "hospital"
        assert result["facility_address"] == "1 Avenue Nelson Mandela"
        assert result["facility_city"] == "Dakar"
        assert result["facility_region"] == "Dakar"

    def test_extract_partial_facility_fields(self):
        """Test extraction partielle des champs facility."""
        sub_extensions = [
            Extension(url="name", valueString="Clinique Madeleine"),
            Extension(url="city", valueString="Thies"),
        ]

        result = _extract_facility_sub_extensions(sub_extensions)

        assert result["facility_name"] == "Clinique Madeleine"
        assert result["facility_type"] is None
        assert result["facility_city"] == "Thies"


class TestExtractFacility:
    """Tests pour _extract_facility()."""

    def test_extract_facility_complete(self):
        """Test extraction facility complete."""
        practitioner = FHIRPractitioner(
            extension=[
                Extension(
                    url=FACILITY_EXTENSION_URL,
                    extension=[
                        Extension(url="name", valueString="CHU Fann"),
                        Extension(url="type", valueString="hospital"),
                        Extension(url="city", valueString="Dakar"),
                    ],
                )
            ]
        )

        result = _extract_facility(practitioner)

        assert result["facility_name"] == "CHU Fann"
        assert result["facility_type"] == "hospital"
        assert result["facility_city"] == "Dakar"

    def test_extract_facility_no_extension(self):
        """Test extraction sans extension."""
        practitioner = FHIRPractitioner(extension=None)

        result = _extract_facility(practitioner)

        assert result["facility_name"] is None
        assert result["facility_type"] is None
        assert result["facility_address"] is None
        assert result["facility_city"] is None
        assert result["facility_region"] is None

    def test_extract_facility_other_extension(self):
        """Test extraction avec autre extension (pas facility)."""
        practitioner = FHIRPractitioner(
            extension=[Extension(url="http://other.extension/url", valueString="other")]
        )

        result = _extract_facility(practitioner)

        assert result["facility_name"] is None


class TestExtractExperience:
    """Tests pour _extract_experience()."""

    def test_extract_experience_present(self):
        """Test extraction experience presente."""
        practitioner = FHIRPractitioner(
            extension=[Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=15)]
        )

        result = _extract_experience(practitioner)

        assert result == 15

    def test_extract_experience_zero(self):
        """Test extraction experience zero (nouveau diplome)."""
        practitioner = FHIRPractitioner(
            extension=[Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=0)]
        )

        result = _extract_experience(practitioner)

        assert result == 0

    def test_extract_experience_none(self):
        """Test extraction sans experience."""
        practitioner = FHIRPractitioner(extension=None)

        result = _extract_experience(practitioner)

        assert result is None


class TestExtractLanguages:
    """Tests pour _extract_languages()."""

    def test_extract_single_language(self):
        """Test extraction langue unique."""
        practitioner = FHIRPractitioner(
            communication=[
                PractitionerCommunication(
                    language=CodeableConcept(coding=[Coding(system="urn:ietf:bcp:47", code="fr")])
                )
            ]
        )

        result = _extract_languages(practitioner)

        assert result == "fr"

    def test_extract_multiple_languages(self):
        """Test extraction langues multiples."""
        practitioner = FHIRPractitioner(
            communication=[
                PractitionerCommunication(
                    language=CodeableConcept(coding=[Coding(system="urn:ietf:bcp:47", code="fr")])
                ),
                PractitionerCommunication(
                    language=CodeableConcept(coding=[Coding(system="urn:ietf:bcp:47", code="en")])
                ),
                PractitionerCommunication(
                    language=CodeableConcept(coding=[Coding(system="urn:ietf:bcp:47", code="wo")])
                ),
            ]
        )

        result = _extract_languages(practitioner)

        assert result == "fr,en,wo"

    def test_extract_no_language_default_fr(self):
        """Test extraction sans langue retourne francais par defaut."""
        practitioner = FHIRPractitioner(communication=None)

        result = _extract_languages(practitioner)

        assert result == "fr"


# =============================================================================
# Tests for builder functions
# =============================================================================


class TestBuildIdentifiers:
    """Tests pour _build_identifiers()."""

    def test_build_both_identifiers(self):
        """Test construction avec keycloak et professional_id."""
        result = _build_identifiers("keycloak-123", "CNOM-456")

        assert len(result) == 2
        assert result[0].system == KEYCLOAK_SYSTEM
        assert result[0].value == "keycloak-123"
        assert result[0].use == "official"
        assert result[1].system == PROFESSIONAL_LICENSE_SYSTEM
        assert result[1].value == "CNOM-456"

    def test_build_keycloak_only(self):
        """Test construction avec keycloak uniquement."""
        result = _build_identifiers("keycloak-only")

        assert len(result) == 1
        assert result[0].system == KEYCLOAK_SYSTEM
        assert result[0].value == "keycloak-only"


class TestBuildName:
    """Tests pour _build_name()."""

    def test_build_name_with_dr_title(self):
        """Test construction nom avec titre Dr."""
        result = _build_name("Amadou", "Diallo", "Dr")

        assert len(result) == 1
        assert result[0].family == "Diallo"
        assert result[0].given == ["Amadou"]
        assert result[0].prefix == ["Dr."]
        assert result[0].use == "official"

    def test_build_name_with_pr_title(self):
        """Test construction nom avec titre Pr."""
        result = _build_name("Fatou", "Ndiaye", "Pr")

        assert result[0].prefix == ["Prof."]

    def test_build_name_with_nurse_title(self):
        """Test construction nom avec titre Infirmier."""
        result = _build_name("Ibrahima", "Sow", "Inf")

        assert result[0].prefix == ["RN"]

    def test_build_name_with_autre_title_no_prefix(self):
        """Test construction nom avec titre Autre (pas de prefix)."""
        result = _build_name("Moussa", "Ba", "Autre")

        # "Autre" maps to "" so no prefix should be added
        assert result[0].prefix is None or result[0].prefix == []


class TestBuildTelecom:
    """Tests pour _build_telecom()."""

    def test_build_all_telecom(self):
        """Test construction avec tous les contacts."""
        result = _build_telecom(
            "dr@africare.sn",
            "+221771234567",
            "+221339876543",
        )

        assert len(result) == 3
        assert result[0].system == "email"
        assert result[0].value == "dr@africare.sn"
        assert result[1].system == "phone"
        assert result[1].value == "+221771234567"
        assert result[2].system == "phone"
        assert result[2].value == "+221339876543"
        assert result[2].rank == 2

    def test_build_telecom_without_secondary(self):
        """Test construction sans telephone secondaire."""
        result = _build_telecom("nurse@hospital.sn", "+221781234567")

        assert len(result) == 2


class TestBuildQualifications:
    """Tests pour _build_qualifications()."""

    def test_build_full_qualifications(self):
        """Test construction qualifications completes."""
        result = _build_qualifications(
            specialty="Cardiologie",
            professional_type="physician",
            sub_specialty="Interventionnelle",
            qualifications="MD, FACC",
        )

        assert len(result) == 4
        # Verify specialty
        assert result[0].code.coding[0].system == "http://africare.app/fhir/specialty"
        assert result[0].code.coding[0].display == "Cardiologie"
        # Verify professional type
        assert result[1].code.coding[0].system == "http://africare.app/fhir/professional-type"
        assert result[1].code.coding[0].code == "physician"
        # Verify sub-specialty
        assert result[2].code.coding[0].system == "http://africare.app/fhir/sub-specialty"
        # Verify qualifications text
        assert result[3].code.coding[0].display == "MD, FACC"

    def test_build_minimal_qualifications(self):
        """Test construction qualifications minimales."""
        result = _build_qualifications(
            specialty="Medecine Generale",
            professional_type="physician",
        )

        assert len(result) == 2  # Only specialty and type

    def test_build_qualifications_nurse_type(self):
        """Test construction avec type infirmier."""
        result = _build_qualifications(
            specialty="Soins Intensifs",
            professional_type="nurse",
        )

        type_qual = result[1]
        assert type_qual.code.coding[0].code == "nurse"
        assert type_qual.code.coding[0].display == "Nurse"


class TestBuildFacilityExtension:
    """Tests pour _build_facility_extension()."""

    def test_build_complete_facility(self):
        """Test construction facility complete."""
        result = _build_facility_extension(
            facility_name="Hopital Principal",
            facility_type="hospital",
            facility_address="123 Rue de la Sante",
            facility_city="Dakar",
            facility_region="Dakar",
        )

        assert result is not None
        assert result.url == FACILITY_EXTENSION_URL
        assert len(result.extension) == 5

    def test_build_partial_facility(self):
        """Test construction facility partielle."""
        result = _build_facility_extension(
            facility_name="Clinique du Point E",
            facility_type=None,
            facility_address=None,
            facility_city="Dakar",
            facility_region=None,
        )

        assert result is not None
        assert len(result.extension) == 2

    def test_build_no_facility(self):
        """Test construction sans facility."""
        result = _build_facility_extension(
            facility_name=None,
            facility_type=None,
            facility_address=None,
            facility_city=None,
            facility_region=None,
        )

        assert result is None


class TestBuildExperienceExtension:
    """Tests pour _build_experience_extension()."""

    def test_build_experience_present(self):
        """Test construction avec experience."""
        result = _build_experience_extension(20)

        assert result is not None
        assert result.url == EXPERIENCE_EXTENSION_URL
        assert result.valueInteger == 20

    def test_build_experience_zero(self):
        """Test construction avec experience zero."""
        result = _build_experience_extension(0)

        assert result is not None
        assert result.valueInteger == 0

    def test_build_experience_none(self):
        """Test construction sans experience."""
        result = _build_experience_extension(None)

        assert result is None


class TestBuildCommunication:
    """Tests pour _build_communication()."""

    def test_build_single_language(self):
        """Test construction langue unique."""
        result = _build_communication("fr")

        assert len(result) == 1
        assert result[0].language.coding[0].code == "fr"

    def test_build_multiple_languages(self):
        """Test construction langues multiples."""
        result = _build_communication("fr,en,wo")

        assert len(result) == 3
        codes = [comm.language.coding[0].code for comm in result]
        assert codes == ["fr", "en", "wo"]

    def test_build_empty_language_defaults_to_fr(self):
        """Test construction avec chaine vide."""
        result = _build_communication("")

        assert len(result) == 1
        assert result[0].language.coding[0].code == "fr"


# =============================================================================
# Tests for apply update functions
# =============================================================================


class TestApplyNameUpdates:
    """Tests pour _apply_name_updates()."""

    def test_apply_first_name_update(self):
        """Test mise a jour du prenom."""
        practitioner = FHIRPractitioner(
            name=[HumanName(family="Diallo", given=["Amadou"], prefix=["Dr."])]
        )
        updates = ProfessionalUpdate(first_name="Moustapha")

        _apply_name_updates(practitioner, updates)

        assert practitioner.name[0].given == ["Moustapha"]
        assert practitioner.name[0].family == "Diallo"

    def test_apply_last_name_update(self):
        """Test mise a jour du nom de famille."""
        practitioner = FHIRPractitioner(name=[HumanName(family="Sow", given=["Fatou"])])
        updates = ProfessionalUpdate(last_name="Ndiaye")

        _apply_name_updates(practitioner, updates)

        assert practitioner.name[0].family == "Ndiaye"
        assert practitioner.name[0].given == ["Fatou"]

    def test_apply_title_update(self):
        """Test mise a jour du titre."""
        practitioner = FHIRPractitioner(
            name=[HumanName(family="Ba", given=["Ibou"], prefix=["Dr."])]
        )
        updates = ProfessionalUpdate(title="Pr")

        _apply_name_updates(practitioner, updates)

        assert practitioner.name[0].prefix == ["Prof."]

    def test_apply_no_name_updates(self):
        """Test sans mise a jour de nom."""
        practitioner = FHIRPractitioner(name=[HumanName(family="Original", given=["Name"])])
        updates = ProfessionalUpdate()

        _apply_name_updates(practitioner, updates)

        assert practitioner.name[0].family == "Original"


class TestApplyTelecomUpdates:
    """Tests pour _apply_telecom_updates()."""

    def test_apply_email_update(self):
        """Test mise a jour de l'email."""
        practitioner = FHIRPractitioner(
            telecom=[
                ContactPoint(system="email", value="old@example.sn"),
                ContactPoint(system="phone", value="+221770000000"),
            ]
        )
        updates = ProfessionalUpdate(email="new@africare.sn")

        _apply_telecom_updates(practitioner, updates)

        # Find email in updated telecom
        emails = [t.value for t in practitioner.telecom if t.system == "email"]
        assert "new@africare.sn" in emails

    def test_apply_phone_update(self):
        """Test mise a jour du telephone."""
        practitioner = FHIRPractitioner(
            telecom=[
                ContactPoint(system="email", value="test@test.sn"),
                ContactPoint(system="phone", value="+221770000000"),
            ]
        )
        updates = ProfessionalUpdate(phone="+221771111111")

        _apply_telecom_updates(practitioner, updates)

        phones = [t.value for t in practitioner.telecom if t.system == "phone"]
        assert "+221771111111" in phones


class TestApplyQualificationUpdates:
    """Tests pour _apply_qualification_updates()."""

    def test_apply_specialty_update(self):
        """Test mise a jour de la specialite."""
        practitioner = FHIRPractitioner(
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="Medecine Generale",
                            )
                        ]
                    )
                )
            ]
        )
        updates = ProfessionalUpdate(specialty="Cardiologie")

        _apply_qualification_updates(practitioner, updates)

        # Check updated specialty
        specialty_qual = next(
            (
                q
                for q in practitioner.qualification
                if q.code.coding[0].system == "http://africare.app/fhir/specialty"
            ),
            None,
        )
        assert specialty_qual is not None
        assert specialty_qual.code.coding[0].display == "Cardiologie"

    def test_apply_sub_specialty_update(self):
        """Test mise a jour de la sous-specialite."""
        practitioner = FHIRPractitioner(
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="Cardiologie",
                            )
                        ]
                    )
                )
            ]
        )
        updates = ProfessionalUpdate(sub_specialty="Interventionnelle")

        _apply_qualification_updates(practitioner, updates)

        # Check sub-specialty was added
        sub_spec_qual = next(
            (
                q
                for q in practitioner.qualification
                if q.code.coding[0].system == "http://africare.app/fhir/sub-specialty"
            ),
            None,
        )
        assert sub_spec_qual is not None


class TestApplyFacilityUpdates:
    """Tests pour _apply_facility_updates()."""

    def test_apply_facility_name_update(self):
        """Test mise a jour du nom de l'etablissement."""
        practitioner = FHIRPractitioner(
            extension=[
                Extension(
                    url=FACILITY_EXTENSION_URL,
                    extension=[Extension(url="name", valueString="Ancien Hopital")],
                )
            ]
        )
        updates = ProfessionalUpdate(facility_name="Nouvel Hopital")

        _apply_facility_updates(practitioner, updates)

        # Find facility extension
        facility_ext = next(
            (e for e in practitioner.extension if e.url == FACILITY_EXTENSION_URL), None
        )
        assert facility_ext is not None
        name_ext = next((e for e in facility_ext.extension if e.url == "name"), None)
        assert name_ext.valueString == "Nouvel Hopital"

    def test_apply_no_facility_updates(self):
        """Test sans mise a jour facility."""
        practitioner = FHIRPractitioner(extension=None)
        updates = ProfessionalUpdate()

        _apply_facility_updates(practitioner, updates)

        # Should not create extension if no updates
        assert practitioner.extension is None or len(practitioner.extension) == 0


class TestApplyExperienceUpdates:
    """Tests pour _apply_experience_updates()."""

    def test_apply_experience_update(self):
        """Test mise a jour de l'experience."""
        practitioner = FHIRPractitioner(
            extension=[Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=5)]
        )
        updates = ProfessionalUpdate(years_of_experience=10)

        _apply_experience_updates(practitioner, updates)

        exp_ext = next(
            (e for e in practitioner.extension if e.url == EXPERIENCE_EXTENSION_URL), None
        )
        assert exp_ext.valueInteger == 10

    def test_apply_experience_update_from_none(self):
        """Test ajout experience quand absente."""
        practitioner = FHIRPractitioner(extension=None)
        updates = ProfessionalUpdate(years_of_experience=3)

        _apply_experience_updates(practitioner, updates)

        assert practitioner.extension is not None
        exp_ext = next(
            (e for e in practitioner.extension if e.url == EXPERIENCE_EXTENSION_URL), None
        )
        assert exp_ext.valueInteger == 3


class TestApplyLanguageUpdates:
    """Tests pour _apply_language_updates()."""

    def test_apply_language_update(self):
        """Test mise a jour des langues."""
        practitioner = FHIRPractitioner(
            communication=[
                PractitionerCommunication(
                    language=CodeableConcept(coding=[Coding(system="urn:ietf:bcp:47", code="fr")])
                )
            ]
        )
        updates = ProfessionalUpdate(languages_spoken="fr,en,wo")

        _apply_language_updates(practitioner, updates)

        assert len(practitioner.communication) == 3
        codes = [c.language.coding[0].code for c in practitioner.communication]
        assert set(codes) == {"fr", "en", "wo"}


# =============================================================================
# Tests for ProfessionalMapper class
# =============================================================================


class TestProfessionalMapperToFhir:
    """Tests pour ProfessionalMapper.to_fhir()."""

    def test_to_fhir_full_professional(self):
        """Test conversion complete vers FHIR."""
        professional = ProfessionalCreate(
            keycloak_user_id="kc-pro-123",
            professional_id="CNOM-12345",
            first_name="Amadou",
            last_name="Diallo",
            title="Dr",
            email="dr.diallo@africare.sn",
            phone="+221771234567",
            phone_secondary="+221339876543",
            specialty="Cardiologie",
            sub_specialty="Interventionnelle",
            professional_type="physician",
            qualifications="MD, FACC",
            facility_name="CHU Fann",
            facility_type="hospital",
            facility_address="Avenue Cheikh Anta Diop",
            facility_city="Dakar",
            facility_region="Dakar",
            years_of_experience=20,
            languages_spoken="fr,en",
        )

        result = ProfessionalMapper.to_fhir(professional)

        assert isinstance(result, FHIRPractitioner)
        assert result.active is True
        # Check identifiers
        assert len(result.identifier) == 2
        # Check name
        assert result.name[0].family == "Diallo"
        assert result.name[0].given == ["Amadou"]
        # Check telecom
        assert len(result.telecom) == 3
        # Check qualifications
        assert len(result.qualification) == 4  # specialty, type, sub-spec, quals text
        # Check extensions (facility + experience)
        assert len(result.extension) == 2
        # Check communication
        assert len(result.communication) == 2

    def test_to_fhir_minimal_professional(self):
        """Test conversion minimale vers FHIR."""
        professional = ProfessionalCreate(
            keycloak_user_id="kc-min-456",
            first_name="Fatou",
            last_name="Sow",
            email="fatou@clinic.sn",
            phone="+221781234567",
            specialty="Medecine Generale",
            professional_type="physician",
        )

        result = ProfessionalMapper.to_fhir(professional)

        assert result.active is True
        assert len(result.identifier) == 1  # Only keycloak
        assert len(result.telecom) == 2  # email + phone
        # No extensions (no facility, no experience)
        assert result.extension is None or len(result.extension) == 0

    def test_to_fhir_nurse_type(self):
        """Test conversion infirmier vers FHIR."""
        professional = ProfessionalCreate(
            keycloak_user_id="kc-nurse-789",
            first_name="Mariama",
            last_name="Ba",
            title="Inf",
            email="mariama@hospital.sn",
            phone="+221771112233",
            specialty="Soins Intensifs",
            professional_type="nurse",
        )

        result = ProfessionalMapper.to_fhir(professional)

        # Check title prefix
        assert result.name[0].prefix == ["RN"]
        # Check professional type
        type_qual = next(
            (
                q
                for q in result.qualification
                if q.code.coding[0].system == "http://africare.app/fhir/professional-type"
            ),
            None,
        )
        assert type_qual.code.coding[0].code == "nurse"


class TestProfessionalMapperFromFhir:
    """Tests pour ProfessionalMapper.from_fhir()."""

    def test_from_fhir_full_professional(self):
        """Test conversion complete depuis FHIR."""
        practitioner = FHIRPractitioner(
            id="fhir-practitioner-123",
            active=True,
            identifier=[
                Identifier(system=KEYCLOAK_SYSTEM, value="kc-from-fhir"),
                Identifier(system=PROFESSIONAL_LICENSE_SYSTEM, value="CNOM-67890"),
            ],
            name=[HumanName(family="Ndiaye", given=["Moussa"], prefix=["Dr."])],
            telecom=[
                ContactPoint(system="email", value="moussa@hospital.sn"),
                ContactPoint(system="phone", value="+221770001122"),
            ],
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="Pediatrie",
                            )
                        ]
                    )
                ),
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/professional-type",
                                code="physician",
                            )
                        ]
                    )
                ),
            ],
            extension=[
                Extension(
                    url=FACILITY_EXTENSION_URL,
                    extension=[
                        Extension(url="name", valueString="Hopital Enfants"),
                        Extension(url="city", valueString="Dakar"),
                    ],
                ),
                Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=15),
            ],
            communication=[
                PractitionerCommunication(
                    language=CodeableConcept(coding=[Coding(system="urn:ietf:bcp:47", code="fr")])
                ),
            ],
        )

        gdpr_metadata = {
            "is_verified": True,
            "is_available": True,
            "digital_signature": "sig123",
            "notes": "Test notes",
            "created_at": datetime(2024, 1, 15, 10, 30, tzinfo=UTC),
            "updated_at": datetime(2024, 6, 20, 14, 45, tzinfo=UTC),
            "created_by": "admin",
            "updated_by": "system",
        }

        result = ProfessionalMapper.from_fhir(
            practitioner, local_id=42, gdpr_metadata=gdpr_metadata
        )

        assert result.id == 42
        assert result.keycloak_user_id == "kc-from-fhir"
        assert result.professional_id == "CNOM-67890"
        assert result.first_name == "Moussa"
        assert result.last_name == "Ndiaye"
        assert result.title == "Dr"
        assert result.email == "moussa@hospital.sn"
        assert result.phone == "+221770001122"
        assert result.specialty == "Pediatrie"
        assert result.professional_type == "physician"
        assert result.facility_name == "Hopital Enfants"
        assert result.facility_city == "Dakar"
        assert result.years_of_experience == 15
        assert result.languages_spoken == "fr"
        assert result.is_active is True
        assert result.is_verified is True
        assert result.digital_signature == "sig123"
        assert result.created_by == "admin"

    def test_from_fhir_empty_metadata(self):
        """Test conversion avec metadata vide."""
        practitioner = FHIRPractitioner(
            active=True,
            identifier=[
                Identifier(system=KEYCLOAK_SYSTEM, value="kc-empty-meta"),
            ],
            name=[HumanName(family="Test", given=["User"])],
            telecom=[
                ContactPoint(system="email", value="test@test.sn"),
                ContactPoint(system="phone", value="+221770000000"),
            ],
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="General",
                            )
                        ]
                    )
                ),
            ],
        )

        result = ProfessionalMapper.from_fhir(practitioner, local_id=1, gdpr_metadata=None)

        assert result.id == 1
        assert result.is_verified is False  # Default
        assert result.is_available is True  # Default
        assert result.digital_signature is None


class TestProfessionalMapperToListItem:
    """Tests pour ProfessionalMapper.to_list_item()."""

    def test_to_list_item(self):
        """Test conversion vers ProfessionalListItem."""
        practitioner = FHIRPractitioner(
            active=True,
            identifier=[
                Identifier(system=KEYCLOAK_SYSTEM, value="kc-list-item"),
            ],
            name=[HumanName(family="Sall", given=["Ibrahima"], prefix=["Dr."])],
            telecom=[
                ContactPoint(system="email", value="ibrahima@clinic.sn"),
                ContactPoint(system="phone", value="+221772223344"),
            ],
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="Chirurgie",
                            )
                        ]
                    )
                ),
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/professional-type",
                                code="physician",
                            )
                        ]
                    )
                ),
            ],
            extension=[
                Extension(
                    url=FACILITY_EXTENSION_URL,
                    extension=[Extension(url="name", valueString="CHU Aristide")],
                ),
            ],
        )

        gdpr = {
            "is_verified": True,
            "is_available": False,
            "created_at": datetime(2024, 3, 1, tzinfo=UTC),
        }

        result = ProfessionalMapper.to_list_item(practitioner, local_id=99, gdpr_metadata=gdpr)

        assert result.id == 99
        assert result.title == "Dr"
        assert result.first_name == "Ibrahima"
        assert result.last_name == "Sall"
        assert result.specialty == "Chirurgie"
        assert result.professional_type == "physician"
        assert result.email == "ibrahima@clinic.sn"
        assert result.facility_name == "CHU Aristide"
        assert result.is_active is True
        assert result.is_verified is True
        assert result.is_available is False


class TestProfessionalMapperApplyUpdates:
    """Tests pour ProfessionalMapper.apply_updates()."""

    def test_apply_all_updates(self):
        """Test application de toutes les mises a jour."""
        practitioner = FHIRPractitioner(
            active=True,
            name=[HumanName(family="Original", given=["Name"])],
            telecom=[
                ContactPoint(system="email", value="old@old.sn"),
                ContactPoint(system="phone", value="+221770000000"),
            ],
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="Old Specialty",
                            )
                        ]
                    )
                ),
            ],
        )

        updates = ProfessionalUpdate(
            first_name="Updated",
            last_name="Name",
            email="new@new.sn",
            specialty="New Specialty",
            facility_name="New Hospital",
            years_of_experience=25,
            languages_spoken="fr,en,wo",
            is_active=False,
        )

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        assert result.active is False
        assert result.name[0].given == ["Updated"]
        assert len(result.communication) == 3

    def test_apply_partial_updates(self):
        """Test application de mises a jour partielles."""
        practitioner = FHIRPractitioner(
            active=True,
            name=[HumanName(family="Keep", given=["This"])],
            telecom=[
                ContactPoint(system="email", value="keep@keep.sn"),
                ContactPoint(system="phone", value="+221771111111"),
            ],
        )

        updates = ProfessionalUpdate(
            phone="+221772222222",
        )

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        # Name should be unchanged
        assert result.name[0].family == "Keep"
        # Phone should be updated
        phones = [t.value for t in result.telecom if t.system == "phone"]
        assert "+221772222222" in phones

    def test_apply_no_updates(self):
        """Test sans aucune mise a jour."""
        practitioner = FHIRPractitioner(
            active=True,
            name=[HumanName(family="Unchanged", given=["Value"])],
        )

        updates = ProfessionalUpdate()

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        assert result.name[0].family == "Unchanged"
        assert result.active is True


class TestProfessionalMapperRoundTrip:
    """Tests aller-retour create -> FHIR -> response."""

    def test_create_to_fhir_to_response(self):
        """Test cycle complet create -> FHIR -> response."""
        original = ProfessionalCreate(
            keycloak_user_id="roundtrip-kc-123",
            professional_id="CNOM-RT456",
            first_name="Roundtrip",
            last_name="Test",
            title="Dr",
            email="roundtrip@test.sn",
            phone="+221773334455",
            specialty="Dermatologie",
            professional_type="physician",
            facility_name="Clinique Test",
            facility_city="Dakar",
            years_of_experience=12,
            languages_spoken="fr,en",
        )

        # Convert to FHIR
        fhir_practitioner = ProfessionalMapper.to_fhir(original)

        # Convert back to response
        gdpr = {
            "is_verified": True,
            "is_available": True,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        response = ProfessionalMapper.from_fhir(fhir_practitioner, local_id=100, gdpr_metadata=gdpr)

        # Verify round-trip preserved data
        assert response.keycloak_user_id == original.keycloak_user_id
        assert response.professional_id == original.professional_id
        assert response.first_name == original.first_name
        assert response.last_name == original.last_name
        assert response.title == original.title
        assert response.email == original.email
        assert response.phone == original.phone
        assert response.specialty == original.specialty
        assert response.professional_type == original.professional_type
        assert response.facility_name == original.facility_name
        assert response.facility_city == original.facility_city
        assert response.years_of_experience == original.years_of_experience
        assert response.languages_spoken == original.languages_spoken

    def test_update_preserves_unchanged_fields(self):
        """Test que les updates preservent les champs non modifies.

        NOTE: La logique actuelle de _apply_name_updates utilise "Dr" par defaut
        quand updates.title est None et qu'un champ name est modifie. Pour preserver
        le titre lors d'une mise a jour de nom, il faut explicitement passer le titre.
        """
        # Create initial practitioner
        original = ProfessionalCreate(
            keycloak_user_id="preserve-kc-789",
            professional_id="CNOM-PRES",
            first_name="Preserve",
            last_name="Fields",
            title="Pr",
            email="preserve@test.sn",
            phone="+221774445566",
            specialty="Neurologie",
            professional_type="physician",
            facility_name="CHU Test",
            years_of_experience=30,
            languages_spoken="fr,wo",
        )

        fhir_practitioner = ProfessionalMapper.to_fhir(original)

        # Apply partial update - include title to preserve it
        updates = ProfessionalUpdate(
            first_name="NewFirst",
            title="Pr",  # Explicitement passer le titre pour le preserver
            sub_specialty="Epileptologie",
        )

        updated = ProfessionalMapper.apply_updates(fhir_practitioner, updates)

        # Convert back
        gdpr = {"is_verified": False, "is_available": True}
        response = ProfessionalMapper.from_fhir(updated, local_id=200, gdpr_metadata=gdpr)

        # Updated fields
        assert response.first_name == "NewFirst"
        assert response.sub_specialty == "Epileptologie"

        # Preserved fields
        assert response.last_name == "Fields"
        assert response.title == "Pr"
        assert response.email == "preserve@test.sn"
        assert response.specialty == "Neurologie"
        assert response.facility_name == "CHU Test"
        assert response.years_of_experience == 30
