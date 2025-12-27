"""Tests unitaires pour ProfessionalMapper.

Ce module teste les fonctions de mapping bidirectionnel entre les schemas Pydantic
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
    PROFESSIONAL_TYPE_CODES,
    TITLE_PREFIX_MAP,
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
# Tests pour les fonctions d'extraction
# =============================================================================


class TestExtractIdentifiers:
    """Tests pour _extract_identifiers()."""

    def test_extract_both_identifiers(self):
        """Test extraction avec keycloak_user_id et professional_id."""
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
        practitioner = FHIRPractitioner()
        result = _extract_identifiers(practitioner)

        assert result["keycloak_user_id"] is None
        assert result["professional_id"] is None

    def test_extract_other_system_identifiers(self):
        """Test extraction avec systemes non reconnus."""
        practitioner = FHIRPractitioner(
            identifier=[
                Identifier(system="http://other.system", value="other-id"),
            ]
        )
        result = _extract_identifiers(practitioner)

        assert result["keycloak_user_id"] is None
        assert result["professional_id"] is None


class TestExtractName:
    """Tests pour _extract_name()."""

    def test_extract_full_name_with_title(self):
        """Test extraction nom complet avec titre."""
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

    def test_extract_name_with_prof_title(self):
        """Test extraction avec titre Professeur."""
        practitioner = FHIRPractitioner(
            name=[
                HumanName(
                    use="official",
                    family="Sow",
                    given=["Ibrahima"],
                    prefix=["Prof."],
                )
            ]
        )
        result = _extract_name(practitioner)

        assert result["first_name"] == "Ibrahima"
        assert result["last_name"] == "Sow"
        assert result["title"] == "Pr"

    def test_extract_family_only(self):
        """Test extraction avec nom de famille uniquement."""
        practitioner = FHIRPractitioner(name=[HumanName(family="Ndiaye")])
        result = _extract_name(practitioner)

        assert result["first_name"] == ""
        assert result["last_name"] == "Ndiaye"
        assert result["title"] == "Dr"  # Default

    def test_extract_no_name(self):
        """Test extraction sans nom."""
        practitioner = FHIRPractitioner()
        result = _extract_name(practitioner)

        assert result["first_name"] == ""
        assert result["last_name"] == ""
        assert result["title"] == "Dr"

    def test_extract_multiple_given_names(self):
        """Test extraction avec plusieurs prenoms."""
        practitioner = FHIRPractitioner(
            name=[
                HumanName(
                    family="Fall",
                    given=["Moussa", "Ibrahima", "Cheikh"],
                )
            ]
        )
        result = _extract_name(practitioner)

        # NOTE: Seul le premier prenom est extrait
        assert result["first_name"] == "Moussa"
        assert result["last_name"] == "Fall"


class TestExtractTelecom:
    """Tests pour _extract_telecom()."""

    def test_extract_all_telecom(self):
        """Test extraction avec tous les telecoms."""
        practitioner = FHIRPractitioner(
            telecom=[
                ContactPoint(system="email", value="dr.diallo@hospital.sn"),
                ContactPoint(system="phone", value="+221771234567"),
                ContactPoint(system="phone", value="+221769876543"),
            ]
        )
        result = _extract_telecom(practitioner)

        assert result["email"] == "dr.diallo@hospital.sn"
        assert result["phone"] == "+221771234567"
        assert result["phone_secondary"] == "+221769876543"

    def test_extract_email_only(self):
        """Test extraction avec email uniquement."""
        practitioner = FHIRPractitioner(
            telecom=[
                ContactPoint(system="email", value="nurse@clinic.sn"),
            ]
        )
        result = _extract_telecom(practitioner)

        assert result["email"] == "nurse@clinic.sn"
        assert result["phone"] is None
        assert result["phone_secondary"] is None

    def test_extract_no_telecom(self):
        """Test extraction sans telecom."""
        practitioner = FHIRPractitioner()
        result = _extract_telecom(practitioner)

        assert result["email"] is None
        assert result["phone"] is None
        assert result["phone_secondary"] is None


class TestExtractQualification:
    """Tests pour _extract_qualification()."""

    def test_extract_full_qualifications(self):
        """Test extraction avec toutes les qualifications."""
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
                                code="pediatric-cardiology",
                                display="Cardiologie pediatrique",
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
        assert result["sub_specialty"] == "Cardiologie pediatrique"
        assert result["professional_type"] == "physician"
        assert result["qualifications"] == "MD, PhD, FACC"

    def test_extract_minimal_qualifications(self):
        """Test extraction avec qualifications minimales."""
        practitioner = FHIRPractitioner(
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="General Medicine",
                            )
                        ]
                    )
                ),
            ]
        )
        result = _extract_qualification(practitioner)

        assert result["specialty"] == "General Medicine"
        assert result["sub_specialty"] is None
        assert result["professional_type"] == "other"
        assert result["qualifications"] is None

    def test_extract_no_qualifications(self):
        """Test extraction sans qualifications."""
        practitioner = FHIRPractitioner()
        result = _extract_qualification(practitioner)

        assert result["specialty"] == ""
        assert result["sub_specialty"] is None
        assert result["professional_type"] == "other"
        assert result["qualifications"] is None

    def test_extract_nurse_type(self):
        """Test extraction pour type infirmier."""
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
        """Test extraction avec tous les champs facility."""
        sub_extensions = [
            Extension(url="name", valueString="Hopital Principal"),
            Extension(url="type", valueString="hospital"),
            Extension(url="address", valueString="123 Rue de la Sante"),
            Extension(url="city", valueString="Dakar"),
            Extension(url="region", valueString="Dakar"),
        ]
        result = _extract_facility_sub_extensions(sub_extensions)

        assert result["facility_name"] == "Hopital Principal"
        assert result["facility_type"] == "hospital"
        assert result["facility_address"] == "123 Rue de la Sante"
        assert result["facility_city"] == "Dakar"
        assert result["facility_region"] == "Dakar"

    def test_extract_partial_facility_fields(self):
        """Test extraction avec champs partiels."""
        sub_extensions = [
            Extension(url="name", valueString="Clinique du Cap"),
            Extension(url="city", valueString="Cap-Vert"),
        ]
        result = _extract_facility_sub_extensions(sub_extensions)

        assert result["facility_name"] == "Clinique du Cap"
        assert result["facility_city"] == "Cap-Vert"
        assert result["facility_type"] is None
        assert result["facility_address"] is None
        assert result["facility_region"] is None


class TestExtractFacility:
    """Tests pour _extract_facility()."""

    def test_extract_facility_with_extension(self):
        """Test extraction avec extension facility."""
        practitioner = FHIRPractitioner(
            extension=[
                Extension(
                    url=FACILITY_EXTENSION_URL,
                    extension=[
                        Extension(url="name", valueString="Centre de Sante"),
                        Extension(url="type", valueString="clinic"),
                        Extension(url="city", valueString="Thies"),
                    ],
                )
            ]
        )
        result = _extract_facility(practitioner)

        assert result["facility_name"] == "Centre de Sante"
        assert result["facility_type"] == "clinic"
        assert result["facility_city"] == "Thies"

    def test_extract_no_facility(self):
        """Test extraction sans facility."""
        practitioner = FHIRPractitioner()
        result = _extract_facility(practitioner)

        assert result["facility_name"] is None
        assert result["facility_type"] is None
        assert result["facility_address"] is None
        assert result["facility_city"] is None
        assert result["facility_region"] is None

    def test_extract_with_other_extensions(self):
        """Test extraction avec autres extensions (pas facility)."""
        practitioner = FHIRPractitioner(
            extension=[
                Extension(
                    url="http://other.extension",
                    valueString="other value",
                )
            ]
        )
        result = _extract_facility(practitioner)

        assert result["facility_name"] is None


class TestExtractExperience:
    """Tests pour _extract_experience()."""

    def test_extract_experience_with_value(self):
        """Test extraction avec experience."""
        practitioner = FHIRPractitioner(
            extension=[Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=15)]
        )
        result = _extract_experience(practitioner)

        assert result == 15

    def test_extract_experience_no_extension(self):
        """Test extraction sans extension."""
        practitioner = FHIRPractitioner()
        result = _extract_experience(practitioner)

        assert result is None

    def test_extract_experience_zero(self):
        """Test extraction avec experience zero (nouveau diplome)."""
        practitioner = FHIRPractitioner(
            extension=[Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=0)]
        )
        result = _extract_experience(practitioner)

        assert result == 0


class TestExtractLanguages:
    """Tests pour _extract_languages()."""

    def test_extract_multiple_languages(self):
        """Test extraction avec plusieurs langues."""
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

    def test_extract_single_language(self):
        """Test extraction avec une seule langue."""
        practitioner = FHIRPractitioner(
            communication=[
                PractitionerCommunication(
                    language=CodeableConcept(coding=[Coding(system="urn:ietf:bcp:47", code="en")])
                ),
            ]
        )
        result = _extract_languages(practitioner)

        assert result == "en"

    def test_extract_no_languages(self):
        """Test extraction sans communication."""
        practitioner = FHIRPractitioner()
        result = _extract_languages(practitioner)

        # Default is "fr"
        assert result == "fr"


# =============================================================================
# Tests pour les fonctions de construction
# =============================================================================


class TestBuildIdentifiers:
    """Tests pour _build_identifiers()."""

    def test_build_both_identifiers(self):
        """Test construction avec les deux identifiants."""
        result = _build_identifiers("keycloak-uuid-789", "CNOM-99999")

        assert len(result) == 2
        assert result[0].system == KEYCLOAK_SYSTEM
        assert result[0].value == "keycloak-uuid-789"
        assert result[0].use == "official"
        assert result[1].system == PROFESSIONAL_LICENSE_SYSTEM
        assert result[1].value == "CNOM-99999"
        assert result[1].use == "official"

    def test_build_keycloak_only(self):
        """Test construction avec keycloak uniquement."""
        result = _build_identifiers("keycloak-only")

        assert len(result) == 1
        assert result[0].system == KEYCLOAK_SYSTEM
        assert result[0].value == "keycloak-only"

    def test_build_with_none_professional_id(self):
        """Test construction avec professional_id None."""
        result = _build_identifiers("kc-id", None)

        assert len(result) == 1


class TestBuildName:
    """Tests pour _build_name()."""

    def test_build_name_with_dr_title(self):
        """Test construction nom avec titre Dr."""
        result = _build_name("Amadou", "Diallo", "Dr")

        assert len(result) == 1
        name = result[0]
        assert name.use == "official"
        assert name.family == "Diallo"
        assert name.given == ["Amadou"]
        assert name.prefix == ["Dr."]

    def test_build_name_with_pr_title(self):
        """Test construction nom avec titre Pr."""
        result = _build_name("Ibrahima", "Sow", "Pr")

        name = result[0]
        assert name.prefix == ["Prof."]

    def test_build_name_with_nurse_title(self):
        """Test construction nom avec titre Infirmier."""
        result = _build_name("Fatou", "Ndiaye", "Inf")

        name = result[0]
        assert name.prefix == ["RN"]

    def test_build_name_with_midwife_title(self):
        """Test construction nom avec titre Sage-femme."""
        result = _build_name("Mariama", "Fall", "Sage-femme")

        name = result[0]
        assert name.prefix == ["MW"]

    def test_build_name_with_autre_title(self):
        """Test construction nom avec titre Autre (pas de prefix)."""
        result = _build_name("Moussa", "Ba", "Autre")

        name = result[0]
        # prefix not set for "Autre" (empty string in mapping)
        assert name.prefix is None or name.prefix == []


class TestBuildTelecom:
    """Tests pour _build_telecom()."""

    def test_build_all_telecom(self):
        """Test construction avec tous les telecoms."""
        result = _build_telecom("dr@hospital.sn", "+221771234567", "+221769876543")

        assert len(result) == 3
        assert result[0].system == "email"
        assert result[0].value == "dr@hospital.sn"
        assert result[0].use == "work"
        assert result[0].rank == 1
        assert result[1].system == "phone"
        assert result[1].value == "+221771234567"
        assert result[1].rank == 1
        assert result[2].system == "phone"
        assert result[2].value == "+221769876543"
        assert result[2].rank == 2

    def test_build_without_secondary_phone(self):
        """Test construction sans telephone secondaire."""
        result = _build_telecom("email@test.sn", "+221770000000")

        assert len(result) == 2


class TestBuildQualifications:
    """Tests pour _build_qualifications()."""

    def test_build_full_qualifications(self):
        """Test construction qualifications completes."""
        result = _build_qualifications(
            specialty="Cardiologie",
            professional_type="physician",
            sub_specialty="Cardiologie interventionnelle",
            qualifications="MD, FACC",
        )

        assert len(result) == 4  # specialty, type, sub-specialty, qualifications

        # Check specialty
        specialty_qual = result[0]
        assert specialty_qual.code.coding[0].system == "http://africare.app/fhir/specialty"
        assert specialty_qual.code.coding[0].code == "cardiologie"
        assert specialty_qual.code.coding[0].display == "Cardiologie"

        # Check professional type
        type_qual = result[1]
        assert type_qual.code.coding[0].system == "http://africare.app/fhir/professional-type"
        assert type_qual.code.coding[0].code == "physician"
        assert type_qual.code.coding[0].display == "Physician"

        # Check sub-specialty
        sub_qual = result[2]
        assert sub_qual.code.coding[0].system == "http://africare.app/fhir/sub-specialty"
        assert sub_qual.code.coding[0].display == "Cardiologie interventionnelle"

        # Check free-text qualifications
        text_qual = result[3]
        assert text_qual.code.coding[0].system == "http://africare.app/fhir/qualifications"
        assert text_qual.code.coding[0].display == "MD, FACC"

    def test_build_minimal_qualifications(self):
        """Test construction qualifications minimales."""
        result = _build_qualifications(
            specialty="General",
            professional_type="nurse",
        )

        assert len(result) == 2  # specialty + type only

    def test_build_qualifications_unknown_type(self):
        """Test construction avec type non reconnu."""
        result = _build_qualifications(
            specialty="Test",
            professional_type="unknown_type",
        )

        type_qual = result[1]
        assert type_qual.code.coding[0].code == "other"
        assert type_qual.code.coding[0].display == "Other"


class TestBuildFacilityExtension:
    """Tests pour _build_facility_extension()."""

    def test_build_full_facility(self):
        """Test construction extension facility complete."""
        result = _build_facility_extension(
            facility_name="Hopital Aristide Le Dantec",
            facility_type="hospital",
            facility_address="30 Avenue Pasteur",
            facility_city="Dakar",
            facility_region="Dakar",
        )

        assert result is not None
        assert result.url == FACILITY_EXTENSION_URL
        assert len(result.extension) == 5

        # Verify sub-extensions
        sub_ext_map = {ext.url: ext.valueString for ext in result.extension}
        assert sub_ext_map["name"] == "Hopital Aristide Le Dantec"
        assert sub_ext_map["type"] == "hospital"
        assert sub_ext_map["address"] == "30 Avenue Pasteur"
        assert sub_ext_map["city"] == "Dakar"
        assert sub_ext_map["region"] == "Dakar"

    def test_build_partial_facility(self):
        """Test construction extension facility partielle."""
        result = _build_facility_extension(
            facility_name="Cabinet Medical",
            facility_type=None,
            facility_address=None,
            facility_city="Saint-Louis",
            facility_region=None,
        )

        assert result is not None
        assert len(result.extension) == 2  # name + city only

    def test_build_no_facility(self):
        """Test construction sans aucune info facility."""
        result = _build_facility_extension(None, None, None, None, None)

        assert result is None


class TestBuildExperienceExtension:
    """Tests pour _build_experience_extension()."""

    def test_build_experience(self):
        """Test construction extension experience."""
        result = _build_experience_extension(25)

        assert result is not None
        assert result.url == EXPERIENCE_EXTENSION_URL
        assert result.valueInteger == 25

    def test_build_no_experience(self):
        """Test construction sans experience."""
        result = _build_experience_extension(None)

        assert result is None

    def test_build_zero_experience(self):
        """Test construction avec experience zero."""
        result = _build_experience_extension(0)

        assert result is not None
        assert result.valueInteger == 0


class TestBuildCommunication:
    """Tests pour _build_communication()."""

    def test_build_multiple_languages(self):
        """Test construction avec plusieurs langues."""
        result = _build_communication("fr,en,wo")

        assert len(result) == 3
        assert result[0].language.coding[0].code == "fr"
        assert result[1].language.coding[0].code == "en"
        assert result[2].language.coding[0].code == "wo"

    def test_build_single_language(self):
        """Test construction avec une seule langue."""
        result = _build_communication("en")

        assert len(result) == 1
        assert result[0].language.coding[0].code == "en"

    def test_build_empty_string(self):
        """Test construction avec chaine vide."""
        result = _build_communication("")

        # Should default to "fr"
        assert len(result) == 1
        assert result[0].language.coding[0].code == "fr"


# =============================================================================
# Tests pour les fonctions d'application de mises a jour
# =============================================================================


class TestApplyNameUpdates:
    """Tests pour _apply_name_updates()."""

    def test_apply_full_name_update(self):
        """Test mise a jour nom complet."""
        practitioner = FHIRPractitioner(name=[HumanName(family="Original", given=["Old"])])
        updates = ProfessionalUpdate(
            first_name="Nouveau",
            last_name="Nom",
            title="Pr",
        )

        _apply_name_updates(practitioner, updates)

        assert practitioner.name[0].family == "Nom"
        assert practitioner.name[0].given == ["Nouveau"]
        assert practitioner.name[0].prefix == ["Prof."]

    def test_apply_partial_name_update(self):
        """Test mise a jour partielle du nom."""
        practitioner = FHIRPractitioner(
            name=[HumanName(family="Diallo", given=["Amadou"], prefix=["Dr."])]
        )
        updates = ProfessionalUpdate(first_name="Moussa")

        _apply_name_updates(practitioner, updates)

        assert practitioner.name[0].given == ["Moussa"]
        assert practitioner.name[0].family == "Diallo"  # Unchanged

    def test_no_name_update(self):
        """Test sans mise a jour du nom."""
        practitioner = FHIRPractitioner(name=[HumanName(family="Keep", given=["This"])])
        updates = ProfessionalUpdate()  # No name fields

        _apply_name_updates(practitioner, updates)

        assert practitioner.name[0].family == "Keep"
        assert practitioner.name[0].given == ["This"]


class TestApplyTelecomUpdates:
    """Tests pour _apply_telecom_updates()."""

    def test_apply_email_update(self):
        """Test mise a jour email."""
        practitioner = FHIRPractitioner(
            telecom=[
                ContactPoint(system="email", value="old@email.sn"),
                ContactPoint(system="phone", value="+221770000000"),
            ]
        )
        updates = ProfessionalUpdate(email="new@email.sn")

        _apply_telecom_updates(practitioner, updates)

        email_contact = next(t for t in practitioner.telecom if t.system == "email")
        assert email_contact.value == "new@email.sn"

    def test_no_telecom_update(self):
        """Test sans mise a jour telecom."""
        practitioner = FHIRPractitioner(
            telecom=[ContactPoint(system="email", value="keep@email.sn")]
        )
        updates = ProfessionalUpdate()

        _apply_telecom_updates(practitioner, updates)

        assert practitioner.telecom[0].value == "keep@email.sn"


class TestApplyQualificationUpdates:
    """Tests pour _apply_qualification_updates()."""

    def test_apply_specialty_update(self):
        """Test mise a jour specialite."""
        practitioner = FHIRPractitioner(
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
            ]
        )
        updates = ProfessionalUpdate(specialty="Neurologie")

        _apply_qualification_updates(practitioner, updates)

        specialty_qual = practitioner.qualification[0]
        assert specialty_qual.code.coding[0].display == "Neurologie"

    def test_no_qualification_update(self):
        """Test sans mise a jour qualification."""
        practitioner = FHIRPractitioner(
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="Keep",
                            )
                        ]
                    )
                ),
            ]
        )
        updates = ProfessionalUpdate()

        _apply_qualification_updates(practitioner, updates)

        # Qualifications unchanged
        assert practitioner.qualification[0].code.coding[0].display == "Keep"


class TestApplyFacilityUpdates:
    """Tests pour _apply_facility_updates()."""

    def test_apply_facility_name_update(self):
        """Test mise a jour nom etablissement."""
        practitioner = FHIRPractitioner(
            extension=[
                Extension(
                    url=FACILITY_EXTENSION_URL,
                    extension=[
                        Extension(url="name", valueString="Old Hospital"),
                    ],
                )
            ]
        )
        updates = ProfessionalUpdate(facility_name="New Hospital")

        _apply_facility_updates(practitioner, updates)

        facility_ext = next(e for e in practitioner.extension if e.url == FACILITY_EXTENSION_URL)
        name_ext = next(e for e in facility_ext.extension if e.url == "name")
        assert name_ext.valueString == "New Hospital"

    def test_add_facility_to_practitioner_without(self):
        """Test ajout facility a un practitioner sans facility."""
        practitioner = FHIRPractitioner()
        updates = ProfessionalUpdate(
            facility_name="New Clinic",
            facility_city="Dakar",
        )

        _apply_facility_updates(practitioner, updates)

        assert practitioner.extension is not None
        assert len(practitioner.extension) == 1
        assert practitioner.extension[0].url == FACILITY_EXTENSION_URL


class TestApplyExperienceUpdates:
    """Tests pour _apply_experience_updates()."""

    def test_apply_experience_update(self):
        """Test mise a jour experience."""
        practitioner = FHIRPractitioner(
            extension=[Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=10)]
        )
        updates = ProfessionalUpdate(years_of_experience=15)

        _apply_experience_updates(practitioner, updates)

        exp_ext = next(e for e in practitioner.extension if e.url == EXPERIENCE_EXTENSION_URL)
        assert exp_ext.valueInteger == 15

    def test_add_experience_to_practitioner_without(self):
        """Test ajout experience a un practitioner sans."""
        practitioner = FHIRPractitioner()
        updates = ProfessionalUpdate(years_of_experience=5)

        _apply_experience_updates(practitioner, updates)

        assert practitioner.extension is not None
        exp_ext = next(e for e in practitioner.extension if e.url == EXPERIENCE_EXTENSION_URL)
        assert exp_ext.valueInteger == 5


class TestApplyLanguageUpdates:
    """Tests pour _apply_language_updates()."""

    def test_apply_language_update(self):
        """Test mise a jour langues."""
        practitioner = FHIRPractitioner(
            communication=[
                PractitionerCommunication(language=CodeableConcept(coding=[Coding(code="fr")])),
            ]
        )
        updates = ProfessionalUpdate(languages_spoken="fr,en,ar")

        _apply_language_updates(practitioner, updates)

        assert len(practitioner.communication) == 3


# =============================================================================
# Tests pour ProfessionalMapper
# =============================================================================


class TestProfessionalMapperToFhir:
    """Tests pour ProfessionalMapper.to_fhir()."""

    def test_to_fhir_full_professional(self):
        """Test conversion professional complet vers FHIR."""
        professional = ProfessionalCreate(
            keycloak_user_id="kc-uuid-full-123",
            professional_id="CNOM-12345",
            first_name="Amadou",
            last_name="Diallo",
            title="Dr",
            email="dr.diallo@hospital.sn",
            phone="+221771234567",
            phone_secondary="+221769876543",
            specialty="Cardiologie",
            sub_specialty="Cardiologie interventionnelle",
            professional_type="physician",
            qualifications="MD, PhD, FACC",
            facility_name="Hopital Principal",
            facility_type="hospital",
            facility_address="123 Rue de la Sante",
            facility_city="Dakar",
            facility_region="Dakar",
            years_of_experience=20,
            languages_spoken="fr,en",
            is_available=True,
        )

        result = ProfessionalMapper.to_fhir(professional)

        # Check type
        assert isinstance(result, FHIRPractitioner)
        assert result.get_resource_type() == "Practitioner"
        assert result.active is True

        # Check identifiers
        assert len(result.identifier) == 2
        kc_id = next(i for i in result.identifier if i.system == KEYCLOAK_SYSTEM)
        assert kc_id.value == "kc-uuid-full-123"
        prof_id = next(i for i in result.identifier if i.system == PROFESSIONAL_LICENSE_SYSTEM)
        assert prof_id.value == "CNOM-12345"

        # Check name
        assert result.name[0].family == "Diallo"
        assert result.name[0].given == ["Amadou"]
        assert result.name[0].prefix == ["Dr."]

        # Check telecom
        assert len(result.telecom) == 3
        email = next(t for t in result.telecom if t.system == "email")
        assert email.value == "dr.diallo@hospital.sn"

        # Check qualifications
        assert len(result.qualification) == 4  # specialty, type, sub, quals

        # Check extensions
        assert result.extension is not None
        facility_ext = next((e for e in result.extension if e.url == FACILITY_EXTENSION_URL), None)
        assert facility_ext is not None
        exp_ext = next((e for e in result.extension if e.url == EXPERIENCE_EXTENSION_URL), None)
        assert exp_ext is not None
        assert exp_ext.valueInteger == 20

        # Check communication
        assert len(result.communication) == 2

    def test_to_fhir_minimal_professional(self):
        """Test conversion professional minimal vers FHIR."""
        professional = ProfessionalCreate(
            keycloak_user_id="kc-minimal-456",
            first_name="Fatou",
            last_name="Ndiaye",
            email="fatou@clinic.sn",
            phone="+221770000000",
            specialty="General",
            professional_type="nurse",
        )

        result = ProfessionalMapper.to_fhir(professional)

        assert isinstance(result, FHIRPractitioner)
        assert result.active is True
        assert len(result.identifier) == 1  # Only keycloak
        assert result.extension is None or len(result.extension) == 0


class TestProfessionalMapperFromFhir:
    """Tests pour ProfessionalMapper.from_fhir()."""

    def test_from_fhir_full_practitioner(self):
        """Test conversion FHIR complet vers ProfessionalResponse."""
        practitioner = FHIRPractitioner(
            id="fhir-uuid-789",
            active=True,
            identifier=[
                Identifier(system=KEYCLOAK_SYSTEM, value="kc-from-fhir"),
                Identifier(system=PROFESSIONAL_LICENSE_SYSTEM, value="CNOM-11111"),
            ],
            name=[
                HumanName(
                    use="official",
                    family="Sow",
                    given=["Ibrahima"],
                    prefix=["Prof."],
                )
            ],
            telecom=[
                ContactPoint(system="email", value="prof.sow@univ.sn"),
                ContactPoint(system="phone", value="+221771111111"),
                ContactPoint(system="phone", value="+221772222222"),
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
                        Extension(url="name", valueString="UCAD"),
                        Extension(url="city", valueString="Dakar"),
                    ],
                ),
                Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=30),
            ],
            communication=[
                PractitionerCommunication(
                    language=CodeableConcept(coding=[Coding(system="urn:ietf:bcp:47", code="fr")])
                ),
                PractitionerCommunication(
                    language=CodeableConcept(coding=[Coding(system="urn:ietf:bcp:47", code="wo")])
                ),
            ],
        )
        gdpr_metadata = {
            "is_verified": True,
            "is_available": True,
            "digital_signature": "sig123",
            "notes": "Professeur emerite",
            "created_at": datetime(2024, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2024, 6, 15, tzinfo=UTC),
            "created_by": "admin",
            "updated_by": "system",
        }

        result = ProfessionalMapper.from_fhir(
            practitioner, local_id=42, gdpr_metadata=gdpr_metadata
        )

        assert result.id == 42
        assert result.keycloak_user_id == "kc-from-fhir"
        assert result.professional_id == "CNOM-11111"
        assert result.first_name == "Ibrahima"
        assert result.last_name == "Sow"
        assert result.title == "Pr"
        assert result.email == "prof.sow@univ.sn"
        assert result.phone == "+221771111111"
        assert result.phone_secondary == "+221772222222"
        assert result.specialty == "Pediatrie"
        assert result.professional_type == "physician"
        assert result.facility_name == "UCAD"
        assert result.facility_city == "Dakar"
        assert result.years_of_experience == 30
        assert result.languages_spoken == "fr,wo"
        assert result.is_active is True
        assert result.is_verified is True
        assert result.is_available is True
        assert result.digital_signature == "sig123"
        assert result.notes == "Professeur emerite"

    def test_from_fhir_empty_metadata(self):
        """Test conversion FHIR avec metadata vide."""
        practitioner = FHIRPractitioner(
            identifier=[
                Identifier(system=KEYCLOAK_SYSTEM, value="kc-empty"),
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

        result = ProfessionalMapper.from_fhir(practitioner, local_id=1)

        assert result.id == 1
        assert result.is_verified is False  # Default
        assert result.is_available is True  # Default


class TestProfessionalMapperToListItem:
    """Tests pour ProfessionalMapper.to_list_item()."""

    def test_to_list_item(self):
        """Test conversion vers ProfessionalListItem."""
        practitioner = FHIRPractitioner(
            active=True,
            name=[HumanName(family="Ba", given=["Ousmane"], prefix=["Dr."])],
            telecom=[
                ContactPoint(system="email", value="dr.ba@hospital.sn"),
                ContactPoint(system="phone", value="+221779999999"),
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
                    extension=[
                        Extension(url="name", valueString="CHU"),
                    ],
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
        assert result.first_name == "Ousmane"
        assert result.last_name == "Ba"
        assert result.specialty == "Chirurgie"
        assert result.professional_type == "physician"
        assert result.email == "dr.ba@hospital.sn"
        assert result.phone == "+221779999999"
        assert result.facility_name == "CHU"
        assert result.is_active is True
        assert result.is_verified is True
        assert result.is_available is False


class TestProfessionalMapperApplyUpdates:
    """Tests pour ProfessionalMapper.apply_updates()."""

    def test_apply_name_update(self):
        """Test application mise a jour nom."""
        practitioner = FHIRPractitioner(name=[HumanName(family="Old", given=["Name"])])
        updates = ProfessionalUpdate(first_name="New", last_name="Person")

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        assert result.name[0].given == ["New"]
        assert result.name[0].family == "Person"

    def test_apply_email_update(self):
        """Test application mise a jour email."""
        practitioner = FHIRPractitioner(
            telecom=[
                ContactPoint(system="email", value="old@email.sn"),
                ContactPoint(system="phone", value="+221770000000"),
            ]
        )
        updates = ProfessionalUpdate(email="new@email.sn")

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        email = next(t for t in result.telecom if t.system == "email")
        assert email.value == "new@email.sn"

    def test_apply_specialty_update(self):
        """Test application mise a jour specialite."""
        practitioner = FHIRPractitioner(
            qualification=[
                PractitionerQualification(
                    code=CodeableConcept(
                        coding=[
                            Coding(
                                system="http://africare.app/fhir/specialty",
                                display="Old",
                            )
                        ]
                    )
                ),
            ]
        )
        updates = ProfessionalUpdate(specialty="Dermatologie")

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        spec = result.qualification[0]
        assert spec.code.coding[0].display == "Dermatologie"

    def test_apply_facility_update(self):
        """Test application mise a jour facility."""
        practitioner = FHIRPractitioner(
            extension=[
                Extension(
                    url=FACILITY_EXTENSION_URL,
                    extension=[
                        Extension(url="name", valueString="Old Facility"),
                    ],
                ),
            ]
        )
        updates = ProfessionalUpdate(facility_name="New Hospital")

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        facility_ext = next(e for e in result.extension if e.url == FACILITY_EXTENSION_URL)
        name_ext = next(e for e in facility_ext.extension if e.url == "name")
        assert name_ext.valueString == "New Hospital"

    def test_apply_experience_update(self):
        """Test application mise a jour experience."""
        practitioner = FHIRPractitioner(
            extension=[
                Extension(url=EXPERIENCE_EXTENSION_URL, valueInteger=5),
            ]
        )
        updates = ProfessionalUpdate(years_of_experience=10)

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        exp_ext = next(e for e in result.extension if e.url == EXPERIENCE_EXTENSION_URL)
        assert exp_ext.valueInteger == 10

    def test_apply_languages_update(self):
        """Test application mise a jour langues."""
        practitioner = FHIRPractitioner(
            communication=[
                PractitionerCommunication(language=CodeableConcept(coding=[Coding(code="fr")])),
            ]
        )
        updates = ProfessionalUpdate(languages_spoken="fr,en,ar")

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        assert len(result.communication) == 3

    def test_apply_active_status_update(self):
        """Test application mise a jour status actif."""
        practitioner = FHIRPractitioner(active=True)
        updates = ProfessionalUpdate(is_active=False)

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        assert result.active is False

    def test_apply_no_updates(self):
        """Test sans mise a jour."""
        practitioner = FHIRPractitioner(
            active=True,
            name=[HumanName(family="Keep", given=["Me"])],
        )
        updates = ProfessionalUpdate()  # Empty

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        assert result.active is True
        assert result.name[0].family == "Keep"
        assert result.name[0].given == ["Me"]

    def test_apply_sub_specialty_update(self):
        """Test application mise a jour sous-specialite."""
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
            ]
        )
        updates = ProfessionalUpdate(sub_specialty="Electrophysiologie")

        result = ProfessionalMapper.apply_updates(practitioner, updates)

        # Should now have 3 qualifications (specialty, type, sub-specialty)
        assert len(result.qualification) == 3


class TestProfessionalMapperRoundTrip:
    """Tests de round-trip create -> to_fhir -> from_fhir."""

    def test_create_to_fhir_to_response(self):
        """Test round-trip complet."""
        original = ProfessionalCreate(
            keycloak_user_id="roundtrip-uuid",
            professional_id="CNOM-99999",
            first_name="Test",
            last_name="RoundTrip",
            title="Pr",
            email="roundtrip@test.sn",
            phone="+221771111111",
            phone_secondary="+221772222222",
            specialty="Neurologie",
            sub_specialty="Epileptologie",
            professional_type="physician",
            qualifications="MD, PhD",
            facility_name="Test Hospital",
            facility_type="hospital",
            facility_address="Test Address",
            facility_city="Dakar",
            facility_region="Dakar",
            years_of_experience=15,
            languages_spoken="fr,en",
            is_available=True,
            notes="Test notes",
        )

        # Convert to FHIR
        fhir_practitioner = ProfessionalMapper.to_fhir(original)

        # Convert back to response
        gdpr_metadata = {
            "is_verified": True,
            "is_available": True,
            "digital_signature": None,
            "notes": "Test notes",
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "created_by": "test",
            "updated_by": "test",
        }
        response = ProfessionalMapper.from_fhir(
            fhir_practitioner,
            local_id=100,
            gdpr_metadata=gdpr_metadata,
        )

        # Verify round-trip preserved data
        assert response.keycloak_user_id == original.keycloak_user_id
        assert response.professional_id == original.professional_id
        assert response.first_name == original.first_name
        assert response.last_name == original.last_name
        assert response.title == original.title
        assert response.email == original.email
        assert response.phone == original.phone
        # NOTE: phone_secondary depends on telecom order in extraction
        assert response.specialty == original.specialty
        assert response.sub_specialty == original.sub_specialty
        assert response.professional_type == original.professional_type
        assert response.qualifications == original.qualifications
        assert response.facility_name == original.facility_name
        assert response.facility_type == original.facility_type
        assert response.facility_address == original.facility_address
        assert response.facility_city == original.facility_city
        assert response.facility_region == original.facility_region
        assert response.years_of_experience == original.years_of_experience
        assert response.languages_spoken == original.languages_spoken

    def test_update_preserves_unchanged_fields(self):
        """Test que les updates preservent les champs non modifies."""
        # Create initial professional
        original = ProfessionalCreate(
            keycloak_user_id="preserve-test",
            first_name="Original",
            last_name="Name",
            email="original@test.sn",
            phone="+221770000000",
            specialty="Medecine Generale",
            professional_type="physician",
            years_of_experience=10,
        )

        fhir = ProfessionalMapper.to_fhir(original)

        # Apply partial update
        updates = ProfessionalUpdate(
            first_name="Updated",
            years_of_experience=12,
        )
        updated_fhir = ProfessionalMapper.apply_updates(fhir, updates)

        # Convert back and check
        response = ProfessionalMapper.from_fhir(updated_fhir, local_id=1)

        # Updated fields
        assert response.first_name == "Updated"
        assert response.years_of_experience == 12

        # Preserved fields
        assert response.last_name == "Name"
        assert response.email == "original@test.sn"
        assert response.specialty == "Medecine Generale"
        assert response.professional_type == "physician"


# =============================================================================
# Tests pour les constantes et mappings
# =============================================================================


class TestConstants:
    """Tests pour les constantes du module."""

    def test_professional_type_codes(self):
        """Test que tous les types ont des codes valides."""
        expected_types = ["physician", "nurse", "midwife", "pharmacist", "technician", "other"]
        for type_key in expected_types:
            assert type_key in PROFESSIONAL_TYPE_CODES
            code, display = PROFESSIONAL_TYPE_CODES[type_key]
            assert isinstance(code, str)
            assert isinstance(display, str)

    def test_title_prefix_map(self):
        """Test que tous les titres ont des prefixes."""
        expected_titles = ["Dr", "Pr", "Inf", "Sage-femme", "Pharmacien", "Autre"]
        for title in expected_titles:
            assert title in TITLE_PREFIX_MAP
