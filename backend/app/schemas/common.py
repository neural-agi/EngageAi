"""Common response schemas."""

from pydantic import BaseModel


class ApiMessage(BaseModel):
    """Basic API message schema."""

    status: str
    message: str


class HealthResponse(BaseModel):
    """Healthcheck response schema."""

    status: str
    service: str
    database: str
