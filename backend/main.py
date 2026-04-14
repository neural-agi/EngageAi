"""Deployment entrypoint for running the FastAPI app as ``main:app``."""

from __future__ import annotations

import logging

import uvicorn

from app.config import get_settings, validate_required_settings
from app.main import app
from app.observability.logging import configure_logging


logger = logging.getLogger(__name__)

__all__ = ["app"]


def main() -> None:
    """Launch uvicorn using the configured host and port."""

    settings = get_settings()
    configure_logging(settings.log_level)

    try:
        validate_required_settings(settings)
    except RuntimeError as exc:
        logger.error(
            "Backend startup aborted due to invalid environment configuration",
            extra={"error": str(exc)},
        )
        raise SystemExit(1) from exc

    logger.info(
        "Launching uvicorn server",
        extra={
            "entrypoint": "main:app",
            "host": settings.backend_host,
            "port": settings.backend_port,
            "environment": settings.environment,
        },
    )
    uvicorn.run(
        "main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
