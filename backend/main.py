"""Deployment entrypoint for running the FastAPI app as ``main:app``."""

from __future__ import annotations

import logging
import os

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
    raw_port = (os.environ.get("PORT") or "").strip()

    try:
        validate_required_settings(settings)
    except RuntimeError as exc:
        logger.error(
            "Backend startup aborted due to invalid environment configuration",
            extra={"error": str(exc)},
        )
        raise SystemExit(1) from exc

    try:
        port = int(raw_port) if raw_port else settings.backend_port
    except ValueError as exc:
        logger.error(
            "Backend startup aborted because PORT is invalid",
            extra={"port": raw_port},
        )
        raise SystemExit(1) from exc

    logger.info(
        "Launching uvicorn server",
        extra={
            "entrypoint": "main:app",
            "host": settings.backend_host,
            "port": port,
            "environment": settings.environment,
        },
    )
    uvicorn.run(
        "main:app",
        host=settings.backend_host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
