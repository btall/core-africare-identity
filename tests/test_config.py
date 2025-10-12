import pytest

from app.core.config import parse_list_from_env


class TestParseListFromEnv:
    """Tests pour la fonction utilitaire parse_list_from_env."""

    def test_parse_direct(self):
        """Test avec une liste Python directe."""
        result = parse_list_from_env(["val1", "val2", "val3"], "test_field")
        assert result == ["val1", "val2", "val3"]

    def test_parse_comma_separated(self):
        """Test avec format virgules."""
        result = parse_list_from_env("val1,val2,val3", "test_field")
        assert result == ["val1", "val2", "val3"]

    def test_parse_comma_separated_with_spaces(self):
        """Test avec format virgules et espaces."""
        result = parse_list_from_env("  val1 , val2 , val3  ", "test_field")
        assert result == ["val1", "val2", "val3"]

    def test_parse_json_format(self):
        """Test avec format JSON."""
        result = parse_list_from_env('["val1","val2","val3"]', "test_field")
        assert result == ["val1", "val2", "val3"]

    def test_parse_json_with_spaces(self):
        """Test avec format JSON et espaces."""
        result = parse_list_from_env('  ["val1", "val2", "val3"]  ', "test_field")
        assert result == ["val1", "val2", "val3"]

    def test_parse_empty_string(self):
        """Test avec chaîne vide."""
        result = parse_list_from_env("", "test_field")
        assert result == []

    def test_parse_whitespace_only(self):
        """Test avec espaces seulement."""
        result = parse_list_from_env("   ", "test_field")
        assert result == []

    def test_parse_single_value(self):
        """Test avec une seule valeur."""
        result = parse_list_from_env("single_value", "test_field")
        assert result == ["single_value"]

    def test_parse_urls(self):
        """Test avec des URLs (cas d'usage réel)."""
        urls = "http://localhost:3000,https://api.example.com,https://app.example.com"
        result = parse_list_from_env(urls, "ALLOWED_ORIGINS")
        assert result == [
            "http://localhost:3000",
            "https://api.example.com",
            "https://app.example.com",
        ]

    def test_parse_hosts_with_wildcards(self):
        """Test avec des hosts incluant des wildcards."""
        hosts = "localhost,127.0.0.1,*.example.com,app.example.com"
        result = parse_list_from_env(hosts, "TRUSTED_HOSTS")
        assert result == ["localhost", "127.0.0.1", "*.example.com", "app.example.com"]

    def test_invalid_json_format(self):
        """Test avec format JSON invalide."""
        with pytest.raises(ValueError, match="Format JSON invalide pour test_field"):
            parse_list_from_env('["val1", "val2"', "test_field")

    def test_invalid_type(self):
        """Test avec type invalide."""
        with pytest.raises(ValueError, match="Valeur invalide pour test_field"):
            parse_list_from_env(123, "test_field")  # type: ignore

    def test_empty_values_filtered(self):
        """Test que les valeurs vides sont filtrées."""
        result = parse_list_from_env("val1,,val2,  ,val3", "test_field")
        assert result == ["val1", "val2", "val3"]

    def test_complex_json_with_commas(self):
        """Test JSON avec valeurs contenant des virgules."""
        json_str = '["value,with,comma","normal_value","another,comma,value"]'
        result = parse_list_from_env(json_str, "test_field")
        assert result == ["value,with,comma", "normal_value", "another,comma,value"]


class TestConfigValidators:
    """Tests pour les validateurs de configuration."""

    def test_allowed_origins_validator(self):
        """Test le validateur ALLOWED_ORIGINS."""
        from app.core.config import Settings

        # Test avec format virgules
        validator = Settings.assemble_cors_origins
        result = validator("http://localhost:3000,https://api.example.com")
        assert result == ["http://localhost:3000", "https://api.example.com"]

    def test_trusted_hosts_validator(self):
        """Test le validateur TRUSTED_HOSTS."""
        from app.core.config import Settings

        validator = Settings.assemble_trusted_hosts
        result = validator("localhost,*.example.com")
        assert result == ["localhost", "*.example.com"]

    def test_supported_locales_validator(self):
        """Test le validateur SUPPORTED_LOCALES."""
        from app.core.config import Settings

        validator = Settings.assemble_supported_locales
        result = validator("fr,en")
        assert result == ["fr", "en"]
