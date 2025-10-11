from fastapi import APIRouter

from app.api.v1 import health
from app.api.v1.endpoints import examples
from app.schemas import COMMON_RESPONSES

# Router principal avec réponses RFC 9457 par défaut
router = APIRouter(responses=COMMON_RESPONSES)

router.include_router(health.router, tags=["health"])
router.include_router(examples.router, prefix="/examples", tags=["examples"])
