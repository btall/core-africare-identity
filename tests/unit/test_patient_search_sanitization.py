"""Tests unitaires pour la sanitization SQL dans la recherche de patients."""

import pytest
from pydantic import ValidationError

from app.schemas.patient import PatientSearchFilters


class TestSanitizedSearchStr:
    """Tests pour le type SanitizedSearchStr (problème #6 CRITIQUE)."""

    def test_normal_search_string_accepted(self):
        """Test que les chaînes normales sont acceptées."""
        filters = PatientSearchFilters(
            first_name="Amadou",
            last_name="Diallo",
        )

        assert filters.first_name == "Amadou"
        assert filters.last_name == "Diallo"

    def test_percent_wildcard_rejected(self):
        """Test que le caractère % (SQL wildcard) est rejeté."""
        with pytest.raises(ValidationError) as exc_info:
            PatientSearchFilters(first_name="Amadou%")

        errors = exc_info.value.errors()
        assert any("%" in str(error) for error in errors)

    def test_underscore_wildcard_rejected(self):
        """Test que le caractère _ (SQL wildcard) est rejeté."""
        with pytest.raises(ValidationError) as exc_info:
            PatientSearchFilters(last_name="Diallo_")

        errors = exc_info.value.errors()
        assert any("_" in str(error) for error in errors)

    def test_backslash_escape_rejected(self):
        """Test que le backslash (escape) est rejeté."""
        with pytest.raises(ValidationError) as exc_info:
            PatientSearchFilters(first_name="Amadou\\")

        errors = exc_info.value.errors()
        assert any("\\\\" in str(error) or "backslash" in str(error).lower() for error in errors)

    def test_sql_wildcard_in_injection_pattern_rejected(self):
        """Test qu'un pattern d'injection SQL avec wildcard est rejeté."""
        # Test avec un pattern qui contient un wildcard SQL dangereux
        with pytest.raises(ValidationError) as exc_info:
            PatientSearchFilters(first_name="admin%' OR '1'='1")

        # Doit rejeter à cause du caractère %
        errors = exc_info.value.errors()
        assert len(errors) > 0
        assert any("%" in str(error) for error in errors)

    def test_search_with_spaces_and_hyphens_accepted(self):
        """Test que les espaces et tirets (chars normaux) sont acceptés."""
        filters = PatientSearchFilters(
            first_name="Jean-Pierre",
            last_name="Ba Diallo",
        )

        assert filters.first_name == "Jean-Pierre"
        assert filters.last_name == "Ba Diallo"

    def test_accented_characters_accepted(self):
        """Test que les caractères accentués sont acceptés."""
        filters = PatientSearchFilters(
            first_name="Sékou",
            last_name="N'Diaye",
        )

        assert filters.first_name == "Sékou"
        assert filters.last_name == "N'Diaye"

    def test_multiple_dangerous_chars_rejected(self):
        """Test que plusieurs caractères dangereux sont tous rejetés."""
        dangerous_inputs = [
            "test%",
            "test_",
            "test\\",
            "%test",
            "_test",
            "\\test",
            "te%st",
            "te_st",
            "te\\st",
        ]

        for dangerous_input in dangerous_inputs:
            with pytest.raises(ValidationError):
                PatientSearchFilters(first_name=dangerous_input)
