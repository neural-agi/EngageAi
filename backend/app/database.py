"""Database helpers for PostgreSQL and development SQLite fallback."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings

try:
    from psycopg import connect as postgres_connect
except ImportError:  # pragma: no cover - depends on runtime environment
    postgres_connect = None


logger = logging.getLogger(__name__)


class Base:
    """Base model type for persistence models."""

    # TODO: replace with the real ORM base if the project adopts one later.
    pass


engine: Any | None = None
SessionLocal: Any | None = None


@dataclass(frozen=True)
class DatabaseConfig:
    """Resolved database configuration for the current runtime mode."""

    mode: str
    url: str
    description: str


def resolve_database_config(
    settings: Settings | None = None,
    *,
    override_url: str | None = None,
    sqlite_path: str | Path | None = None,
) -> DatabaseConfig:
    """Resolve PostgreSQL or development SQLite configuration."""

    settings = settings or get_settings()
    configured_url = (override_url or settings.database_url or "").strip()
    if configured_url:
        normalized_url = _normalize_postgres_url(configured_url)
        return DatabaseConfig(
            mode="postgres",
            url=normalized_url,
            description="PostgreSQL",
        )

    environment = settings.environment.strip().lower()
    if environment == "production":
        raise RuntimeError(
            "DATABASE_URL is required in production. "
            "Set DATABASE_URL to a reachable PostgreSQL DSN such as "
            "'postgresql+psycopg://user:password@host:5432/database'."
        )

    fallback_path = Path(sqlite_path) if sqlite_path is not None else _default_sqlite_path()
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    return DatabaseConfig(
        mode="sqlite-dev",
        url=str(fallback_path),
        description=f"SQLite dev fallback at {fallback_path}",
    )


def test_database_connection(
    settings: Settings | None = None,
    *,
    override_url: str | None = None,
    sqlite_path: str | Path | None = None,
) -> tuple[bool, DatabaseConfig, str | None]:
    """Test the configured database connection and return an actionable status."""

    database_config = resolve_database_config(
        settings=settings,
        override_url=override_url,
        sqlite_path=sqlite_path,
    )

    if database_config.mode == "postgres":
        if postgres_connect is None:
            return (
                False,
                database_config,
                "psycopg is not installed. Install backend dependencies with "
                "'pip install -r backend/requirements.txt'.",
            )

        try:
            with postgres_connect(database_config.url, autocommit=True) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:  # pragma: no cover - depends on environment/database
            return (
                False,
                database_config,
                "Unable to connect to PostgreSQL using DATABASE_URL. "
                "Verify the database is running, the URL is correct, and network access is available. "
                f"Original error: {exc}",
            )

        return True, database_config, None

    try:
        with sqlite3.connect(database_config.url) as connection:
            connection.execute("SELECT 1")
    except sqlite3.Error as exc:  # pragma: no cover - depends on filesystem/runtime
        return (
            False,
            database_config,
            "Unable to initialize the SQLite development fallback database. "
            f"Original error: {exc}",
        )

    return True, database_config, None


def get_db() -> Generator[Any, None, None]:
    """Yield a database session placeholder."""

    # TODO: implement shared request/session connection handling if needed.
    if False:
        yield None


def init_db(settings: Settings | None = None) -> DatabaseConfig:
    """Validate database connectivity and return the resolved configuration."""

    ok, database_config, error_message = test_database_connection(settings=settings)
    if not ok:
        raise RuntimeError(error_message or "Database connection check failed.")
    return database_config


def _default_sqlite_path() -> Path:
    """Return the fallback SQLite path for development-only execution."""

    return Path(__file__).resolve().parents[1] / "data" / "dev_memory.sqlite3"


def _normalize_postgres_url(database_url: str) -> str:
    """Normalize SQLAlchemy-style PostgreSQL URLs for psycopg."""

    normalized_database_url = database_url.strip()
    if normalized_database_url.startswith("postgresql+psycopg://"):
        return normalized_database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return normalized_database_url
