"""Health router."""

from fastapi import APIRouter, Request

from app.config import get_settings
from app.schemas.common import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def healthcheck(request: Request) -> HealthResponse:
    """Return a healthcheck response."""

    settings = get_settings()
    database_status = getattr(request.app.state, "database_status", "error")
    return HealthResponse(status="ok", service=settings.app_name, database=database_status)
