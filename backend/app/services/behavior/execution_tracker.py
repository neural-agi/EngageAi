"""Database-backed tracking for asynchronous pipeline executions."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import get_settings
from app.database import resolve_database_config

try:
    from psycopg import connect as postgres_connect
    from psycopg.rows import dict_row as postgres_dict_row
except ImportError:  # pragma: no cover - depends on runtime environment
    postgres_connect = None
    postgres_dict_row = None


class ExecutionLimitExceededError(RuntimeError):
    """Raised when an account exceeds the configured execution cap."""

    def __init__(self, account_id: str, current_count: int, limit: int) -> None:
        """Store context about the rejected execution attempt."""

        super().__init__("Daily execution limit reached")
        self.account_id = account_id
        self.current_count = current_count
        self.limit = limit


class ExecutionTracker:
    """Persist and query background pipeline execution state."""

    _schema_lock = Lock()
    _initialized_targets: set[tuple[str, str]] = set()

    def __init__(
        self,
        database_url: str | None = None,
        sqlite_path: str | Path | None = None,
    ) -> None:
        """Resolve the active database backend and ensure schema exists."""

        settings = get_settings()
        self.database_config = resolve_database_config(
            settings=settings,
            override_url=database_url,
            sqlite_path=sqlite_path,
        )
        self._initialize_schema()

    def create_execution(
        self,
        execution_id: str,
        account_id: str,
        niche_text: str,
        mock: bool,
    ) -> None:
        """Create a pending execution record."""

        now = self._timestamp()
        self._execute(
            """
            INSERT INTO pipeline_executions (
                execution_id,
                account_id,
                niche_text,
                mode,
                status,
                results_json,
                error_message,
                created_at,
                updated_at,
                started_at,
                completed_at
            )
            VALUES ($1, $2, $3, $4, 'pending', NULL, NULL, CAST($5 AS TIMESTAMPTZ), CAST($5 AS TIMESTAMPTZ), NULL, NULL)
            """,
            """
            INSERT INTO pipeline_executions (
                execution_id,
                account_id,
                niche_text,
                mode,
                status,
                results_json,
                error_message,
                created_at,
                updated_at,
                started_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, 'pending', NULL, NULL, ?, ?, NULL, NULL)
            """,
            postgres_params=(execution_id, account_id, niche_text, self._mode(mock), now),
            sqlite_params=(execution_id, account_id, niche_text, self._mode(mock), now, now),
        )

    def create_execution_with_limit(
        self,
        execution_id: str,
        account_id: str,
        niche_text: str,
        mock: bool,
        max_executions_per_day: int,
    ) -> int:
        """Create a pending execution record if the account is still within its daily limit."""

        safe_limit = max(int(max_executions_per_day), 1)
        now = self._timestamp()
        cutoff = self._timestamp_at(datetime.now(timezone.utc) - timedelta(hours=24))

        if self._is_postgres():
            return self._create_execution_with_limit_postgres(
                execution_id=execution_id,
                account_id=account_id,
                niche_text=niche_text,
                mock=mock,
                now=now,
                cutoff=cutoff,
                max_executions_per_day=safe_limit,
            )

        return self._create_execution_with_limit_sqlite(
            execution_id=execution_id,
            account_id=account_id,
            niche_text=niche_text,
            mock=mock,
            now=now,
            cutoff=cutoff,
            max_executions_per_day=safe_limit,
        )

    def mark_running(self, execution_id: str) -> None:
        """Mark an execution as running."""

        now = self._timestamp()
        self._execute(
            """
            UPDATE pipeline_executions
            SET status = 'running',
                updated_at = CAST($2 AS TIMESTAMPTZ),
                started_at = COALESCE(started_at, CAST($2 AS TIMESTAMPTZ)),
                error_message = NULL
            WHERE execution_id = $1
            """,
            """
            UPDATE pipeline_executions
            SET status = 'running',
                updated_at = ?,
                started_at = COALESCE(started_at, ?),
                error_message = NULL
            WHERE execution_id = ?
            """,
            postgres_params=(execution_id, now),
            sqlite_params=(now, now, execution_id),
        )

    def mark_completed(self, execution_id: str, results: list[dict[str, Any]]) -> None:
        """Mark an execution as completed and persist results."""

        now = self._timestamp()
        results_json = json.dumps(results, ensure_ascii=True)
        self._execute(
            """
            UPDATE pipeline_executions
            SET status = 'completed',
                results_json = $2,
                error_message = NULL,
                updated_at = CAST($3 AS TIMESTAMPTZ),
                completed_at = CAST($3 AS TIMESTAMPTZ)
            WHERE execution_id = $1
            """,
            """
            UPDATE pipeline_executions
            SET status = 'completed',
                results_json = ?,
                error_message = NULL,
                updated_at = ?,
                completed_at = ?
            WHERE execution_id = ?
            """,
            postgres_params=(execution_id, results_json, now),
            sqlite_params=(results_json, now, now, execution_id),
        )

    def mark_failed(self, execution_id: str, error_message: str) -> None:
        """Mark an execution as failed and persist the error."""

        now = self._timestamp()
        self._execute(
            """
            UPDATE pipeline_executions
            SET status = 'failed',
                error_message = $2,
                updated_at = CAST($3 AS TIMESTAMPTZ),
                completed_at = CAST($3 AS TIMESTAMPTZ)
            WHERE execution_id = $1
            """,
            """
            UPDATE pipeline_executions
            SET status = 'failed',
                error_message = ?,
                updated_at = ?,
                completed_at = ?
            WHERE execution_id = ?
            """,
            postgres_params=(execution_id, error_message, now),
            sqlite_params=(error_message, now, now, execution_id),
        )

    def update_mode(self, execution_id: str, mode: str) -> None:
        """Update one execution mode label."""

        normalized_mode = self._mode(mode)
        now = self._timestamp()
        self._execute(
            """
            UPDATE pipeline_executions
            SET mode = $2,
                updated_at = CAST($3 AS TIMESTAMPTZ)
            WHERE execution_id = $1
            """,
            """
            UPDATE pipeline_executions
            SET mode = ?,
                updated_at = ?
            WHERE execution_id = ?
            """,
            postgres_params=(execution_id, normalized_mode, now),
            sqlite_params=(normalized_mode, now, execution_id),
        )

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        """Return one execution record with parsed results."""

        row = self._fetch_one(
            """
            SELECT execution_id, account_id, niche_text, mode, status, results_json, error_message,
                   created_at, updated_at, started_at, completed_at
            FROM pipeline_executions
            WHERE execution_id = $1
            """,
            """
            SELECT execution_id, account_id, niche_text, mode, status, results_json, error_message,
                   created_at, updated_at, started_at, completed_at
            FROM pipeline_executions
            WHERE execution_id = ?
            """,
            (execution_id,),
        )
        if row is None:
            return None

        results_json = str(row["results_json"]).strip() if row["results_json"] is not None else ""
        results = json.loads(results_json) if results_json else []
        return {
            "execution_id": row["execution_id"],
            "account_id": row["account_id"],
            "niche_text": row["niche_text"],
            "mode": row["mode"],
            "status": row["status"],
            "results": results,
            "result_count": len(results),
            "error": row["error_message"],
            "created_at": self._serialize_timestamp(row["created_at"]),
            "updated_at": self._serialize_timestamp(row["updated_at"]),
            "started_at": self._serialize_timestamp(row["started_at"]),
            "completed_at": self._serialize_timestamp(row["completed_at"]),
        }

    def list_executions(self, account_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent executions for one account ordered by newest first."""

        normalized_account_id = account_id.strip()
        safe_limit = max(int(limit), 1)
        rows = self._fetch_all(
            """
            SELECT execution_id, status, results_json, error_message, started_at, completed_at
            FROM pipeline_executions
            WHERE account_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            """
            SELECT execution_id, status, results_json, error_message, started_at, completed_at
            FROM pipeline_executions
            WHERE account_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (normalized_account_id, safe_limit),
        )
        executions: list[dict[str, Any]] = []
        for row in rows:
            results = self._parse_results_json(row["results_json"])
            executions.append(
                {
                    "execution_id": row["execution_id"],
                    "status": row["status"],
                    "result_count": len(results),
                    "started_at": self._serialize_timestamp(row["started_at"]),
                    "completed_at": self._serialize_timestamp(row["completed_at"]),
                    "error": row["error_message"],
                }
            )

        return executions

    def _initialize_schema(self) -> None:
        """Create the execution tracking table if needed."""

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
        """Create the PostgreSQL tracking table."""

        if postgres_connect is None:
            raise RuntimeError("psycopg is required for PostgreSQL-backed execution tracking.")

        with postgres_connect(self.database_config.url, autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_executions (
                    execution_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    niche_text TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    results_json TEXT,
                    error_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pipeline_executions_status
                ON pipeline_executions (status, updated_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pipeline_executions_account_created
                ON pipeline_executions (account_id, created_at DESC)
                """
            )

    def _initialize_sqlite_schema(self) -> None:
        """Create the SQLite tracking table."""

        with self._sqlite_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_executions (
                    execution_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    niche_text TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    results_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pipeline_executions_status
                ON pipeline_executions (status, updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_pipeline_executions_account_created
                ON pipeline_executions (account_id, created_at DESC)
                """
            )

    def _create_execution_with_limit_postgres(
        self,
        *,
        execution_id: str,
        account_id: str,
        niche_text: str,
        mock: bool,
        now: str,
        cutoff: str,
        max_executions_per_day: int,
    ) -> int:
        """Atomically enforce the execution cap before inserting a pending execution."""

        if postgres_connect is None:
            raise RuntimeError("psycopg is required for PostgreSQL-backed execution tracking.")

        with postgres_connect(self.database_config.url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (account_id,))
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM pipeline_executions
                WHERE account_id = %s
                  AND created_at >= CAST(%s AS TIMESTAMPTZ)
                """,
                (account_id, cutoff),
            )
            current_count = int(cursor.fetchone()[0])
            if current_count >= max_executions_per_day:
                raise ExecutionLimitExceededError(account_id, current_count, max_executions_per_day)

            cursor.execute(
                """
                INSERT INTO pipeline_executions (
                    execution_id,
                    account_id,
                    niche_text,
                    mode,
                    status,
                    results_json,
                    error_message,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at
                )
                VALUES (%s, %s, %s, %s, 'pending', NULL, NULL, CAST(%s AS TIMESTAMPTZ), CAST(%s AS TIMESTAMPTZ), NULL, NULL)
                """,
                (execution_id, account_id, niche_text, self._mode(mock), now, now),
            )

        return current_count + 1

    def _create_execution_with_limit_sqlite(
        self,
        *,
        execution_id: str,
        account_id: str,
        niche_text: str,
        mock: bool,
        now: str,
        cutoff: str,
        max_executions_per_day: int,
    ) -> int:
        """Atomically enforce the execution cap before inserting a pending execution in SQLite."""

        with self._sqlite_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT COUNT(*) AS execution_count
                FROM pipeline_executions
                WHERE account_id = ?
                  AND created_at >= ?
                """,
                (account_id, cutoff),
            ).fetchone()
            current_count = int(row["execution_count"]) if row is not None else 0
            if current_count >= max_executions_per_day:
                raise ExecutionLimitExceededError(account_id, current_count, max_executions_per_day)

            connection.execute(
                """
                INSERT INTO pipeline_executions (
                    execution_id,
                    account_id,
                    niche_text,
                    mode,
                    status,
                    results_json,
                    error_message,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at
                )
                VALUES (?, ?, ?, ?, 'pending', NULL, NULL, ?, ?, NULL, NULL)
                """,
                (execution_id, account_id, niche_text, self._mode(mock), now, now),
            )

        return current_count + 1

    def _fetch_one(self, postgres_sql: str, sqlite_sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        """Fetch one row from the active backend."""

        if self._is_postgres():
            if postgres_connect is None or postgres_dict_row is None:
                raise RuntimeError("psycopg is required for PostgreSQL-backed execution tracking.")
            with postgres_connect(self.database_config.url) as connection, connection.cursor(
                row_factory=postgres_dict_row
            ) as cursor:
                cursor.execute(postgres_sql, params)
                row = cursor.fetchone()
                return dict(row) if row is not None else None

        with self._sqlite_connection() as connection:
            row = connection.execute(sqlite_sql, params).fetchone()
            return dict(row) if row is not None else None

    def _fetch_all(self, postgres_sql: str, sqlite_sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        """Fetch multiple rows from the active backend."""

        if self._is_postgres():
            if postgres_connect is None or postgres_dict_row is None:
                raise RuntimeError("psycopg is required for PostgreSQL-backed execution tracking.")
            with postgres_connect(self.database_config.url) as connection, connection.cursor(
                row_factory=postgres_dict_row
            ) as cursor:
                cursor.execute(postgres_sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]

        with self._sqlite_connection() as connection:
            rows = connection.execute(sqlite_sql, params).fetchall()
            return [dict(row) for row in rows]

    def _execute(
        self,
        postgres_sql: str,
        sqlite_sql: str,
        *,
        postgres_params: tuple[Any, ...],
        sqlite_params: tuple[Any, ...],
    ) -> None:
        """Execute a write statement against the active backend."""

        if self._is_postgres():
            if postgres_connect is None:
                raise RuntimeError("psycopg is required for PostgreSQL-backed execution tracking.")
            with postgres_connect(self.database_config.url) as connection, connection.cursor() as cursor:
                cursor.execute(postgres_sql, postgres_params)
            return

        with self._sqlite_connection() as connection:
            connection.execute(sqlite_sql, sqlite_params)

    def _sqlite_connection(self) -> sqlite3.Connection:
        """Return a SQLite connection with row access by column name."""

        connection = sqlite3.connect(self.database_config.url)
        connection.row_factory = sqlite3.Row
        return connection

    def _is_postgres(self) -> bool:
        """Return whether the active backend is PostgreSQL."""

        return self.database_config.mode == "postgres"

    def _mode(self, mock: bool | str) -> str:
        """Return the normalized execution mode label."""

        if isinstance(mock, str):
            normalized_mode = mock.strip().lower()
            return normalized_mode or "real"
        return "mock" if mock else "real"

    def _timestamp(self) -> str:
        """Return the current UTC timestamp in ISO format."""

        return datetime.now(timezone.utc).isoformat()

    def _timestamp_at(self, value: datetime) -> str:
        """Return one UTC timestamp value in ISO format."""

        return value.astimezone(timezone.utc).isoformat()

    def _serialize_timestamp(self, value: Any) -> str | None:
        """Serialize database timestamps into ISO strings."""

        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        normalized_value = str(value).strip()
        return normalized_value or None

    def _parse_results_json(self, value: Any) -> list[dict[str, Any]]:
        """Parse one stored results payload into a list."""

        results_json = str(value).strip() if value is not None else ""
        if not results_json:
            return []

        try:
            parsed_results = json.loads(results_json)
        except json.JSONDecodeError:
            return []

        return parsed_results if isinstance(parsed_results, list) else []
