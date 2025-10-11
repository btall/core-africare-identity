from opentelemetry.instrumentation import auto_instrumentation
auto_instrumentation.initialize()

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

# Import automatique de tous les handlers d'événements
import app.events
from app.api.v1 import api as api_v1
# Future versions: uncomment when ready
# from app.api.v2 import api as api_v2
# from app.api.v3 import api as api_v3
from app.core.config import settings
from app.core.events import lifespan as events_lifespan
from fastapi_errors_rfc9457 import RFC9457Config, setup_rfc9457_handlers
from app.core.database import create_db_and_tables
from app.services import event_service

# Configuration du logging standard
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
azure_eventhub_logger = logging.getLogger("azure.eventhub")
azure_eventhub_logger.setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gère le cycle de vie de l'application:
    - Initialise le système d'événements (redis).
    - Crée les tables de base de données.
    - Démarre les consommateurs d'événements.
    - Arrête proprement les services.
    """
    await create_db_and_tables()

    # Utiliser le lifespan des événements (redis)
    async with events_lifespan(app), asyncio.TaskGroup() as tg:
        # Démarrer tous les consommateurs d'événements
        try:
            logger.info("Démarrage du consommateur pour ")
            tg.create_task(
                event_service.start_eventhub_consumer_(),
                name="consumer_"
            )
            logger.info("Application startup complete.")
            yield
        finally:
            # Arrêter tous les consommateurs
            logger.info("Arrêt des consommateurs d'événements...")
logger.info("Application shutdown complete.")


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
    include_error_pages=True,  # Mount error documentation pages
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
app.include_router(
    api_v1.router,
    prefix=settings.get_api_prefix("v1"),
    tags=["v1"]
)

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
