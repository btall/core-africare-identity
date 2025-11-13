from fastapi import APIRouter

from app.api.v1 import health
from app.api.v1.endpoints import admin_professionals, patients, professionals, statistics, webhooks
from app.schemas import COMMON_RESPONSES

# Router principal avec réponses RFC 9457 par défaut
router = APIRouter(responses=COMMON_RESPONSES)

router.include_router(health.router, tags=["health"])
router.include_router(patients.router, prefix="/patients", tags=["patients"])
router.include_router(professionals.router, prefix="/professionals", tags=["professionals"])
router.include_router(statistics.router, prefix="/statistics", tags=["statistics"])
router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
router.include_router(
    admin_professionals.router, prefix="/admin/professionals", tags=["admin-professionals"]
)
