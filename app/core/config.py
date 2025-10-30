import json
import urllib.parse
from typing import Literal, TypeAlias

from opentelemetry.sdk.resources import Resource
from pydantic import AnyHttpUrl, PostgresDsn, computed_field, field_validator
from pydantic_settings import BaseSettings

# Type personnalisé pour les listes configurables depuis l'environnement
ConfigurableList: TypeAlias = str | list[str] | list[AnyHttpUrl]


def parse_list_from_env(value: ConfigurableList, field_name: str = "field") -> list[str]:
    """
    Fonction utilitaire pour parser une liste depuis une variable d'environnement.

    Supporte les formats suivants:
    - Liste Python directe: ['val1', 'val2']
    - Format JSON: '["val1", "val2"]'
    - Format virgules: "val1,val2,val3"
    - Chaîne vide: "" → []

    Args:
        value: La valeur à parser (chaîne ou liste)
        field_name: Nom du champ pour les messages d'erreur

    Returns:
        Liste de chaînes parsée

    Raises:
        ValueError: Si le format n'est pas valide
    """
    if isinstance(value, list):
        return value
    elif isinstance(value, str):
        value = value.strip()
        # Si c'est du JSON (commence par [ et finit par ])
        if value.startswith("[") and value.endswith("]"):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                raise ValueError(f"Format JSON invalide pour {field_name}: {value}")
        # Sinon, traiter comme une chaîne séparée par des virgules
        elif value:
            return [item.strip() for item in value.split(",") if item.strip()]
        else:
            return []
    raise ValueError(f"Valeur invalide pour {field_name}: {value}")


class Settings(BaseSettings):
    # Importation de la version depuis __init__.py (suppose qu'il est défini là)
    try:
        from app import __version__
    except ImportError:
        __version__ = "0.1.0"  # Version par défaut si non trouvée

    PROJECT_NAME: str = "core-africare-identity"
    PROJECT_SLUG: str = "identity"
    VERSION: str = __version__
    DESCRIPTION: str = "Identity management and Keycloak integration"

    # API Versioning - Support multiple versions simultaneously
    API_VERSIONS: list[str] = ["v1"]  # Add "v2", "v3" as needed
    API_LATEST_VERSION: str = "v1"

    # Environnement
    ENVIRONMENT: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = False

    # JWT (si nécessaire pour l'authentification)
    API_GATEWAY_URL: AnyHttpUrl = "http://api-gateway-service:8000"

    # Keycloak Authentication (bearer-only mode - client_secret not needed)
    KEYCLOAK_SERVER_URL: str
    KEYCLOAK_REALM: str
    KEYCLOAK_CLIENT_ID: str
    # KEYCLOAK_CLIENT_SECRET: str  # Not needed for bearer-only clients

    # Webhook Security
    WEBHOOK_SECRET: str  # Secret partagé pour vérifier la signature des webhooks Keycloak
    WEBHOOK_SIGNATURE_TOLERANCE: int = 300  # Tolérance timestamp en secondes (5 min)

    # OpenTelemetry
    OTEL_SERVICE_NAME: str
    OTEL_EXPORTER_OTLP_ENDPOINT: str
    OTEL_EXPORTER_OTLP_PROTOCOL: str
    OTEL_EXPORTER_OTLP_INSECURE: bool
    OTEL_LOG_LEVEL: str = "info"
    # OpenTelemetry Exporters
    OTEL_LOGS_EXPORTER: Literal["otlp", "console"] = "otlp"
    OTEL_TRACES_EXPORTER: Literal["otlp", "console"] = "otlp"
    OTEL_METRICS_EXPORTER: Literal["otlp", "console"] = "otlp"
    # Ces valeurs sont souvent définies par les bibliothèques d'instrumentation, mais peuvent être surchargées
    OTEL_PYTHON_LOG_LEVEL: str = "info"
    OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED: bool = True
    OTEL_PYTHON_LOG_CORRELATION: bool = True
    OTEL_PYTHON_LOG_FORMAT: str = "%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] [trace_id=%(otelTraceID)s span_id=%(otelSpanID)s resource.service.name=%(otelServiceName)s trace_sampled=%(otelTraceSampled)s] - %(message)s"

    # CORS
    # Définir dans .env, ex: ALLOWED_ORIGINS='["http://localhost:3000","https://myfrontend.com"]'
    ALLOWED_ORIGINS: ConfigurableList = []
    # Définir dans .env, ex: TRUSTED_HOSTS='["localhost","127.0.0.1"]'
    TRUSTED_HOSTS: ConfigurableList = ["localhost", "127.0.0.1"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: ConfigurableList) -> list[str]:
        """
        Permet de définir ALLOWED_ORIGINS de plusieurs façons:
        - Chaîne séparée par des virgules: "http://localhost:3000,https://api.exemple.com"
        - Format JSON: '["http://localhost:3000","https://api.exemple.com"]'
        - Liste Python directe (si déjà parsée)
        """
        return parse_list_from_env(v, "ALLOWED_ORIGINS")

    @field_validator("TRUSTED_HOSTS", mode="before")
    @classmethod
    def assemble_trusted_hosts(cls, v: ConfigurableList) -> list[str]:
        """Parse TRUSTED_HOSTS depuis une variable d'environnement."""
        return parse_list_from_env(v, "TRUSTED_HOSTS")

    # Messaging Backend (Phase 1 MVP: Redis, Phase 2+: Azure Event Hub)
    MESSAGING_BACKEND: Literal["redis", "eventhub"] = "redis"

    # Deployment Configuration
    DEPLOYMENT_TARGET: Literal["local", "azure-aca"] = "local"
    DEPLOYMENT_PHASE: Literal[
        "phase1-mvp", "phase2-extension", "phase3-scaling", "phase4-national"
    ] = "phase1-mvp"

    # Base de données
    # PostgreSQL avec SQLAlchemy 2.0
    SQLALCHEMY_DATABASE_URI: PostgresDsn

    # Redis Messaging (Phase 1 MVP)
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_DB: int = 0

    # Internationalisation (i18n)
    # Liste des langues supportées, ex: ["en", "fr"]
    SUPPORTED_LOCALES: ConfigurableList = ["fr", "en"]
    DEFAULT_LOCALE: str = "fr"  # Langue par défaut

    @field_validator("SUPPORTED_LOCALES", mode="before")
    @classmethod
    def assemble_supported_locales(cls, v: ConfigurableList) -> list[str]:
        """Parse SUPPORTED_LOCALES depuis une variable d'environnement."""
        return parse_list_from_env(v, "SUPPORTED_LOCALES")

    # Ressource OpenTelemetry
    @property
    def OTEL_RESOURCE_ATTRIBUTES(self) -> Resource:  # noqa: N802
        """Crée l'objet Resource pour OpenTelemetry avec les attributs du service."""
        return Resource(
            attributes={
                "service.name": self.OTEL_SERVICE_NAME,
                "service.version": self.VERSION,
                "service.environment": self.ENVIRONMENT,
                # Convertir le booléen en chaîne pour les attributs OTEL
                "service.debug": str(self.DEBUG).lower(),
            }
        )

    @computed_field
    @property
    def api_gateway_url(self) -> str:
        """API Gateway URL with latest API version."""
        joined_url = urllib.parse.urljoin(
            str(self.API_GATEWAY_URL), f"/api/{self.API_LATEST_VERSION}"
        )
        return joined_url

    def get_api_prefix(self, version: str | None = None) -> str:
        """
        Get API prefix for a specific version.

        Args:
            version: API version (e.g., "v1", "v2"). Defaults to latest.

        Returns:
            API prefix string (e.g., "/api/v1")
        """
        version = version or self.API_LATEST_VERSION
        return f"/api/{version}"

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"  # Ignorer les variables d'environnement non définies (ex: KEYCLOAK_CLIENT_SECRET)


# Instance unique des paramètres chargée depuis .env
settings = Settings()
