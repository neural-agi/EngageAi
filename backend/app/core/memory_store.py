"""Database-backed memory store for engagement history and counters."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Iterable

from app.config import get_settings
from app.database import resolve_database_config

try:
    from psycopg import connect as postgres_connect
    from psycopg.rows import dict_row as postgres_dict_row
except ImportError:  # pragma: no cover - depends on runtime environment
    postgres_connect = None
    postgres_dict_row = None


logger = logging.getLogger(__name__)


class MemoryStore:
    """Persist shared state between workflow stages in the configured database."""

    _schema_lock = Lock()
    _initialized_targets: set[tuple[str, str]] = set()

    def __init__(
        self,
        file_path: str | Path | None = None,
        account_id: str | None = None,
        database_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self.database_config = resolve_database_config(
            settings=settings,
            override_url=database_url,
            sqlite_path=file_path,
        )
        self.account_id = self._normalize_account_id(account_id)
        self._initialize_schema()

    def set_account_id(self, account_id: str) -> None:
        """Bind the store to a specific account scope."""

        self.account_id = self._normalize_account_id(account_id)

    def put(self, key: str, value: Any) -> None:
        """Store a value by key for the active account."""

        key = key.strip()
        if key == "last_persona_id":
            self._upsert_persona_state(last_persona_id=str(value).strip() or None)
            return
        if key == "last_run_timestamp":
            timestamp = str(value).strip() if value is not None else ""
            self._upsert_persona_state(last_run_timestamp=timestamp or None)
            return
        if key == "generated_comments" and isinstance(value, list):
            self.remember_generated_comments(str(item) for item in value)
            return
        if key == "style_usage" and isinstance(value, dict):
            self._replace_style_usage(value)
            return
        if key == "execution_history" and isinstance(value, list):
            for record in value:
                if isinstance(record, dict):
                    self.remember_execution(record)
            return
        logger.warning("Unsupported memory key", extra={"key": key})

    def get(self, key: str) -> Any | None:
        """Fetch a previously stored value for the active account."""

        key = key.strip()
        if key == "generated_comments":
            return sorted(self.get_generated_comments())
        if key == "style_usage":
            return self.get_style_usage()
        if key == "execution_history":
            return self.get_execution_history()
        if key == "last_persona_id":
            return self._get_persona_state().get("last_persona_id")
        if key == "last_run_timestamp":
            return self._get_persona_state().get("last_run_timestamp")
        logger.warning("Unsupported memory key lookup", extra={"key": key})
        return None

    def get_generated_comments(self) -> set[str]:
        """Return normalized comment texts stored across previous runs."""

        account_id = self.account_id
        if not account_id:
            return set()
        rows = self._fetch_all(
            "SELECT comment_text FROM generated_comments WHERE account_id = $1",
            "SELECT comment_text FROM generated_comments WHERE account_id = ?",
            (account_id,),
        )
        return {
            self.normalize_comment_text(str(row["comment_text"]))
            for row in rows
            if str(row["comment_text"]).strip()
        }

    def remember_generated_comments(self, comments: Iterable[str]) -> None:
        """Persist a batch of generated comments for the active account."""

        account_id = self._require_account_id()
        normalized_comments = {
            self.normalize_comment_text(comment)
            for comment in comments
            if self.normalize_comment_text(comment)
        }
        if not normalized_comments:
            return
        for comment_text in normalized_comments:
            self._execute(
                """
                INSERT INTO generated_comments (account_id, comment_text, created_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (account_id, comment_text) DO NOTHING
                """,
                """
                INSERT OR IGNORE INTO generated_comments (account_id, comment_text, created_at)
                VALUES (?, ?, ?)
                """,
                (account_id, comment_text, self._current_timestamp()),
            )

    def get_style_usage(self) -> dict[str, int]:
        """Return persisted style usage counters for the active account."""

        account_id = self.account_id
        if not account_id:
            return {}
        rows = self._fetch_all(
            "SELECT style, usage_count FROM style_usage WHERE account_id = $1",
            "SELECT style, usage_count FROM style_usage WHERE account_id = ?",
            (account_id,),
        )
        return {
            str(row["style"]): max(0, int(row["usage_count"]))
            for row in rows
        }

    def increment_style_usage(self, style: str, amount: int = 1) -> None:
        """Increment a persisted usage counter for a comment style."""

        account_id = self._require_account_id()
        style = style.strip()
        if not style or amount <= 0:
            return
        self._execute(
            """
            INSERT INTO style_usage (account_id, style, usage_count, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (account_id, style)
            DO UPDATE SET
                usage_count = style_usage.usage_count + EXCLUDED.usage_count,
                updated_at = NOW()
            """,
            """
            INSERT INTO style_usage (account_id, style, usage_count, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account_id, style)
            DO UPDATE SET
                usage_count = style_usage.usage_count + excluded.usage_count,
                updated_at = excluded.updated_at
            """,
            (account_id, style, amount, self._current_timestamp()),
        )

    def get_execution_history(self) -> list[dict[str, Any]]:
        """Return persisted execution history records for the active account."""

        account_id = self.account_id
        if not account_id:
            return []
        rows = self._fetch_all(
            """
            SELECT post_id, comment_text, persona, executed_at
            FROM executions
            WHERE account_id = $1
            ORDER BY executed_at DESC
            """,
            """
            SELECT post_id, comment_text, persona, executed_at
            FROM executions
            WHERE account_id = ?
            ORDER BY executed_at DESC
            """,
            (account_id,),
        )
        return [
            {
                "post_id": str(row["post_id"]).strip(),
                "comment_text": str(row["comment_text"]).strip(),
                "persona": str(row["persona"]).strip() if row["persona"] is not None else "",
                "timestamp": self._serialize_timestamp(row["executed_at"]),
            }
            for row in rows
        ]

    def has_execution_for_post(self, post_id: str) -> bool:
        """Check whether a post already has an execution record."""

        account_id = self.account_id
        post_id = post_id.strip()
        if not account_id or not post_id:
            return False
        row = self._fetch_one(
            "SELECT 1 FROM executions WHERE account_id = $1 AND post_id = $2 LIMIT 1",
            "SELECT 1 FROM executions WHERE account_id = ? AND post_id = ? LIMIT 1",
            (account_id, post_id),
        )
        return row is not None

    def remember_execution(self, record: dict[str, Any]) -> None:
        """Persist a simulated execution record."""

        account_id = self._require_account_id()
        if not isinstance(record, dict):
            return
        post_id = str(record.get("post_id", "")).strip()
        if not post_id:
            return
        comment_text = str(record.get("comment_text", "")).strip()
        persona = str(record.get("persona", "")).strip() or None
        timestamp = str(record.get("timestamp", "")).strip() or self._current_timestamp()
        self._execute(
            """
            INSERT INTO executions (account_id, post_id, comment_text, persona, executed_at)
            VALUES ($1, $2, $3, $4, CAST($5 AS TIMESTAMPTZ))
            ON CONFLICT (account_id, post_id) DO NOTHING
            """,
            """
            INSERT OR IGNORE INTO executions (account_id, post_id, comment_text, persona, executed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (account_id, post_id, comment_text, persona, timestamp),
        )

    def get_last_run_timestamp(self) -> str | None:
        """Return the persisted timestamp for the last completed scheduler run."""

        value = self._get_persona_state().get("last_run_timestamp")
        if isinstance(value, str) and value.strip():
            return value
        return None

    def set_last_run_timestamp(self, timestamp: str) -> None:
        """Persist the timestamp for the last completed scheduler run."""

        timestamp = timestamp.strip()
        if not timestamp:
            return
        self._upsert_persona_state(last_run_timestamp=timestamp)

    def count_executions_for_day(self, target_day: date | None = None) -> int:
        """Count successful executions recorded for a calendar day."""

        account_id = self.account_id
        if not account_id:
            return 0
        if target_day is None:
            target_day = date.today()
        start = datetime.combine(target_day, time.min, tzinfo=timezone.utc).isoformat()
        end = (datetime.combine(target_day, time.min, tzinfo=timezone.utc) + timedelta(days=1)).isoformat()
        row = self._fetch_one(
            """
            SELECT COUNT(*) AS count
            FROM executions
            WHERE account_id = $1
              AND executed_at >= CAST($2 AS TIMESTAMPTZ)
              AND executed_at < CAST($3 AS TIMESTAMPTZ)
            """,
            """
            SELECT COUNT(*) AS count
            FROM executions
            WHERE account_id = ?
              AND executed_at >= ?
              AND executed_at < ?
            """,
            (account_id, start, end),
        )
        return int(row["count"]) if row is not None else 0

    def delete_account_state(self) -> None:
        """Delete all persisted memory rows for the active account."""

        account_id = self._require_account_id()
        self._execute("DELETE FROM executions WHERE account_id = $1", "DELETE FROM executions WHERE account_id = ?", (account_id,))
        self._execute("DELETE FROM generated_comments WHERE account_id = $1", "DELETE FROM generated_comments WHERE account_id = ?", (account_id,))
        self._execute("DELETE FROM style_usage WHERE account_id = $1", "DELETE FROM style_usage WHERE account_id = ?", (account_id,))
        self._execute("DELETE FROM personas WHERE account_id = $1", "DELETE FROM personas WHERE account_id = ?", (account_id,))

    def _get_persona_state(self) -> dict[str, Any]:
        """Return persona/scheduler state for the active account."""

        account_id = self.account_id
        if not account_id:
            return {"last_persona_id": None, "last_run_timestamp": None}
        row = self._fetch_one(
            """
            SELECT last_persona_id, last_run_timestamp
            FROM personas
            WHERE account_id = $1
            """,
            """
            SELECT last_persona_id, last_run_timestamp
            FROM personas
            WHERE account_id = ?
            """,
            (account_id,),
        )
        if row is None:
            return {"last_persona_id": None, "last_run_timestamp": None}
        return {
            "last_persona_id": row["last_persona_id"],
            "last_run_timestamp": self._serialize_timestamp(row["last_run_timestamp"]),
        }

    def _upsert_persona_state(
        self,
        *,
        last_persona_id: str | None = None,
        last_run_timestamp: str | None = None,
    ) -> None:
        """Insert or update persisted persona/scheduler state."""

        account_id = self._require_account_id()
        self._execute(
            """
            INSERT INTO personas (account_id, last_persona_id, last_run_timestamp, updated_at)
            VALUES ($1, $2, CAST($3 AS TIMESTAMPTZ), NOW())
            ON CONFLICT (account_id)
            DO UPDATE SET
                last_persona_id = COALESCE(EXCLUDED.last_persona_id, personas.last_persona_id),
                last_run_timestamp = COALESCE(EXCLUDED.last_run_timestamp, personas.last_run_timestamp),
                updated_at = NOW()
            """,
            """
            INSERT INTO personas (account_id, last_persona_id, last_run_timestamp, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account_id)
            DO UPDATE SET
                last_persona_id = COALESCE(excluded.last_persona_id, personas.last_persona_id),
                last_run_timestamp = COALESCE(excluded.last_run_timestamp, personas.last_run_timestamp),
                updated_at = excluded.updated_at
            """,
            (account_id, last_persona_id, last_run_timestamp, self._current_timestamp()),
        )

    def _replace_style_usage(self, usage: dict[str, Any]) -> None:
        """Replace persisted style usage counters for the active account."""

        account_id = self._require_account_id()
        normalized_usage: dict[str, int] = {}
        for style, value in usage.items():
            style = str(style).strip()
            if not style:
                continue
            try:
                normalized_usage[style] = max(0, int(value))
            except (TypeError, ValueError):
                continue

        self._execute("DELETE FROM style_usage WHERE account_id = $1", "DELETE FROM style_usage WHERE account_id = ?", (account_id,))
        for style, count in normalized_usage.items():
            self._execute(
                """
                INSERT INTO style_usage (account_id, style, usage_count, updated_at)
                VALUES ($1, $2, $3, NOW())
                """,
                """
                INSERT INTO style_usage (account_id, style, usage_count, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (account_id, style, count, self._current_timestamp()),
            )

    def _fetch_all(self, postgres_sql: str, sqlite_sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        """Fetch rows from the active backend."""

        if self._is_postgres():
            if postgres_connect is None or postgres_dict_row is None:
                raise RuntimeError("psycopg is required for PostgreSQL-backed MemoryStore.")
            with postgres_connect(self.database_config.url) as connection, connection.cursor(row_factory=postgres_dict_row) as cursor:
                cursor.execute(postgres_sql, params[: postgres_sql.count("$")])
                return [dict(row) for row in cursor.fetchall()]

        with self._sqlite_connection() as connection:
            rows = connection.execute(sqlite_sql, params).fetchall()
            return [dict(row) for row in rows]

    def _fetch_one(self, postgres_sql: str, sqlite_sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        """Fetch one row from the active backend."""

        rows = self._fetch_all(postgres_sql, sqlite_sql, params)
        return rows[0] if rows else None

    def _execute(self, postgres_sql: str, sqlite_sql: str, params: tuple[Any, ...]) -> None:
        """Execute a write statement against the active backend."""

        if self._is_postgres():
            if postgres_connect is None:
                raise RuntimeError("psycopg is required for PostgreSQL-backed MemoryStore.")
            with postgres_connect(self.database_config.url) as connection, connection.cursor() as cursor:
                cursor.execute(postgres_sql, params[: postgres_sql.count("$")])
            return

        with self._sqlite_connection() as connection:
            connection.execute(sqlite_sql, params)

    def _initialize_schema(self) -> None:
        """Create database tables if they do not already exist."""

        target_key = (self.database_config.mode, self.database_config.url)
        if target_key in self._initialized_targets:
            return

        with self._schema_lock:
            if target_key in self._initialized_targets:
                return

            if self._is_postgres():
                self._initialize_postgres_schema()
            else:
                self._initialize_sqlite_schema()

            self._initialized_targets.add(target_key)

    def _initialize_postgres_schema(self) -> None:
        """Create PostgreSQL tables if they do not already exist."""

        if postgres_connect is None:
            raise RuntimeError("psycopg is required for PostgreSQL-backed MemoryStore.")
        with postgres_connect(self.database_config.url, autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    account_id TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    comment_text TEXT NOT NULL,
                    persona TEXT,
                    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (account_id, post_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_executions_account_timestamp
                ON executions (account_id, executed_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS generated_comments (
                    account_id TEXT NOT NULL,
                    comment_text TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (account_id, comment_text)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS style_usage (
                    account_id TEXT NOT NULL,
                    style TEXT NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (account_id, style)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS personas (
                    account_id TEXT PRIMARY KEY,
                    last_persona_id TEXT,
                    last_run_timestamp TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    def _initialize_sqlite_schema(self) -> None:
        """Create SQLite tables for development fallback."""

        with self._sqlite_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    account_id TEXT NOT NULL,
                    post_id TEXT NOT NULL,
                    comment_text TEXT NOT NULL,
                    persona TEXT,
                    executed_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, post_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_executions_account_timestamp
                ON executions (account_id, executed_at DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS generated_comments (
                    account_id TEXT NOT NULL,
                    comment_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, comment_text)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS style_usage (
                    account_id TEXT NOT NULL,
                    style TEXT NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, style)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS personas (
                    account_id TEXT PRIMARY KEY,
                    last_persona_id TEXT,
                    last_run_timestamp TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _sqlite_connection(self) -> sqlite3.Connection:
        """Return a SQLite connection with row access by column name."""

        connection = sqlite3.connect(self.database_config.url)
        connection.row_factory = sqlite3.Row
        return connection

    def _is_postgres(self) -> bool:
        """Return whether the active backend is PostgreSQL."""

        return self.database_config.mode == "postgres"

    def _require_account_id(self) -> str:
        """Return the active account scope or raise when unset."""

        if not self.account_id:
            raise RuntimeError("MemoryStore requires an account_id before use.")
        return self.account_id

    def _normalize_account_id(self, account_id: str | None) -> str | None:
        """Normalize account identifiers for storage."""

        if account_id is None:
            return None
        normalized_account_id = account_id.strip()
        return normalized_account_id or None

    def _serialize_timestamp(self, value: Any) -> str | None:
        """Serialize stored timestamps into ISO strings."""

        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        normalized_value = str(value).strip()
        return normalized_value or None

    def _current_timestamp(self) -> str:
        """Return the current UTC timestamp in ISO format."""

        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def normalize_comment_text(text: str) -> str:
        """Normalize comment text for memory lookups."""

        return " ".join(str(text).lower().split())
