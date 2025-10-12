import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session

logger = logging.getLogger(__name__)

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok", "error"] = Field(..., description="The status of the health check")


@router.get("/health", tags=["health"], response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_session)):
    try:
        result = await db.execute(select(text("1")))
        result.scalar_one()

        return HealthResponse(status="ok")
    except Exception as e:
        logger.error(f"Error checking health: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to check health: {e!s}") from None
