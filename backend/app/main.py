"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_cors_origins, get_settings, validate_required_settings
from app.database import init_db
from app.observability.logging import configure_logging
from app.routers.campaigns import pipeline_router, router as campaigns_router
from app.routers.health import router as health_router


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure logging, validate env, and emit startup/shutdown logs."""

    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "Loading backend environment configuration",
        extra={"environment": settings.environment},
    )

    try:
        validated_settings = validate_required_settings(settings)
    except RuntimeError as exc:
        logger.error(
            "Backend startup aborted due to invalid environment configuration",
            extra={"error": str(exc)},
        )
        raise

    app.state.settings = validated_settings

    try:
        database_config = init_db(validated_settings)
    except RuntimeError as exc:
        logger.error("Database initialization failed", extra={"error": str(exc)})
        raise

    app.state.database_status = "disabled" if database_config.mode == "memory-only" else "ok"
    app.state.database_mode = database_config.mode
    if database_config.mode == "memory-only":
        logger.warning(
            "Database not configured, running in memory-only mode",
            extra={"database_description": database_config.description},
        )
    elif database_config.mode == "sqlite-dev":
        logger.warning(
            "Running without PostgreSQL (dev mode only)",
            extra={"database_description": database_config.description},
        )
    else:
        logger.info(
            "Database connection verified",
            extra={"database_description": database_config.description},
        )

    logger.info(
        "Starting FastAPI application",
        extra={
            "app_name": validated_settings.app_name,
            "environment": validated_settings.environment,
            "backend_host": validated_settings.backend_host,
            "backend_port": validated_settings.backend_port,
            "database_mode": database_config.mode,
        },
    )
    yield
    logger.info("Shutting down FastAPI application", extra={"app_name": validated_settings.app_name})


app = FastAPI(
    title="EngageAI",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(campaigns_router)
app.include_router(pipeline_router)


@app.get("/")
async def root() -> dict[str, str]:
    """Return the root API placeholder response."""

    return {
        "status": "ok",
        "message": "EngageAI API running",
    }


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return structured JSON for request validation failures."""

    logger.warning(
        "Request validation failed",
        extra={"path": request.url.path, "errors": exc.errors()},
    )
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "message": "Request validation failed.",
            "details": exc.errors(),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return structured JSON for HTTP exceptions."""

    logger.warning(
        "HTTP exception raised",
        extra={"path": request.url.path, "status_code": exc.status_code, "detail": exc.detail},
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "message": str(exc.detail),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return structured JSON for unexpected exceptions."""

    logger.exception("Unhandled application exception", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error.",
        },
    )
