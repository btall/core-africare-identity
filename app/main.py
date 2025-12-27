from opentelemetry.instrumentation import auto_instrumentation

auto_instrumentation.initialize()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi_errors_rfc9457 import RFC9457Config, setup_rfc9457_handlers

# Import automatique de tous les handlers d'événements
import app.events
from app.api.v1 import api as api_v1

# Future versions: uncomment when ready
# from app.api.v2 import api as api_v2
# from app.api.v3 import api as api_v3
from app.core.config import settings
from app.core.database import create_db_and_tables
from app.core.events import lifespan as events_lifespan
from app.core.webhook_streams import (
    close_webhook_redis,
    init_webhook_redis,
    register_webhook_handler,
    start_webhook_consumer,
    stop_webhook_consumer,
)
from app.infrastructure.fhir.client import close_fhir_client, initialize_fhir_client
from app.services.webhook_processor import route_webhook_event

# from app.services import event_service  # Disabled - using Redis instead of Azure Event Hub

logger = logging.getLogger(__name__)
# azure_eventhub_logger = logging.getLogger("azure.eventhub")  # Disabled - not using Azure Event Hub
# azure_eventhub_logger.setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gère le cycle de vie de l'application:
    - Initialise le client FHIR (httpx async).
    - Initialise le système d'événements (Redis Pub/Sub + Streams).
    - Crée les tables de base de données.
    - Démarre les consommateurs d'événements et webhook worker.
    - Arrête proprement les services.
    """
    logger.info("=== Application Startup ===")

    # 1. Initialiser le client FHIR (singleton module-level)
    await initialize_fhir_client(
        base_url=settings.HAPI_FHIR_BASE_URL,
        timeout=settings.HAPI_FHIR_TIMEOUT,
    )
    logger.info(f"Client FHIR initialisé: {settings.HAPI_FHIR_BASE_URL}")

    # 2. Créer les tables de base de données
    await create_db_and_tables()
    logger.info("Tables de base de données créées")

    # 3. Utiliser le lifespan des événements (Redis Pub/Sub)
    async with events_lifespan(app):
        try:
            # 4. Initialiser Redis Streams pour webhooks
            await init_webhook_redis()
            logger.info("Redis Streams initialisé pour webhooks")

            # 5. Enregistrer le handler webhook
            register_webhook_handler(route_webhook_event)
            logger.info("Handler webhook enregistré")

            # 6. Démarrer le consumer webhook en background
            await start_webhook_consumer()
            logger.info("Webhook consumer démarré en background")

            logger.info("=== Application Startup Complete ===")
            yield

        finally:
            # Arrêter tous les consommateurs et fermer les clients
            logger.info("=== Application Shutdown ===")
            await stop_webhook_consumer()
            await close_webhook_redis()
            await close_fhir_client()
            logger.info("Client FHIR fermé")
            logger.info("=== Application Shutdown Complete ===")


# Confirmation shutdown (pour logs)
logger.info("Application module loaded")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    lifespan=lifespan,
    openapi_url=f"{settings.get_api_prefix()}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Exception handlers RFC 9457 Problem Details
config_rfc9457 = RFC9457Config(
    base_url="about:blank",  # Auto-detect request domain
    include_trace_id=True,  # Include OpenTelemetry trace_id
    expose_internal_errors=settings.DEBUG,  # Show detailed errors in dev
    include_error_pages=False,  # Mount error documentation pages (disabled - no error-pages dir)
)
setup_rfc9457_handlers(app, config=config_rfc9457)

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin) for origin in settings.ALLOWED_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware Trusted Hosts
if settings.ENVIRONMENT != "development":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.TRUSTED_HOSTS,
    )

# Include API v1 (current version)
app.include_router(api_v1.router, prefix=settings.get_api_prefix("v1"))

# Future versions: uncomment when ready
# app.include_router(
#     api_v2.router,
#     prefix=settings.get_api_prefix("v2"),
#     tags=["v2"]
# )
# app.include_router(
#     api_v3.router,
#     prefix=settings.get_api_prefix("v3"),
#     tags=["v3"]
# )
