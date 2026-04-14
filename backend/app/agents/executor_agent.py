"""Execution agent for final comment actions."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from app.core.memory_store import MemoryStore
from app.services.behavior.execution_service import ExecutionService


logger = logging.getLogger(__name__)


class ExecutorAgent:
    """
    Executes actions such as posting comments.
    """

    def __init__(
        self,
        simulation_mode: bool = True,
        max_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
        max_comments_per_run: int = 5,
        memory_store: MemoryStore | None = None,
        execution_service: ExecutionService | None = None,
    ) -> None:
        """Initialize safe execution settings."""

        self.simulation_mode = simulation_mode
        self.max_attempts = max(1, max_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self.max_comments_per_run = max(1, max_comments_per_run)
        self.memory_store = memory_store or MemoryStore()
        self.execution_service = execution_service or ExecutionService(memory_store=self.memory_store)
        self._executions_this_run = 0

    def start_run(self) -> None:
        """Reset per-run execution counters."""

        self._executions_this_run = 0

    async def execute(self, post_id: str, comment: Dict) -> Dict:
        """
        Execute the final action (posting a comment).

        Returns:
        {
            "status": "success" | "skipped" | "duplicate",
            "message": str
        }
        """

        validation_error = self._validate_comment(post_id=post_id, comment=comment)
        if validation_error is not None:
            logger.warning(
                "Execution input validation failed",
                extra={"post_id": post_id, "error": validation_error},
            )
            return {
                "status": "skipped",
                "message": validation_error,
            }

        if self._executions_this_run >= self.max_comments_per_run:
            logger.info(
                "Skipping execution because the per-run limit was reached",
                extra={
                    "post_id": post_id,
                    "max_comments_per_run": self.max_comments_per_run,
                },
            )
            return {
                "status": "skipped",
                "message": "Execution limit reached for this run.",
            }

        last_error: str | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                logger.info(
                    "Starting comment execution attempt",
                    extra={
                        "post_id": post_id,
                        "attempt": attempt,
                        "simulation_mode": self.simulation_mode,
                    },
                )

                result = await self._execute_once(post_id=post_id, comment=comment)

                if result.get("status") == "success":
                    self._executions_this_run += 1

                logger.info(
                    "Comment execution completed",
                    extra={
                        "post_id": post_id,
                        "attempt": attempt,
                        "status": result.get("status"),
                    },
                )
                return result
            except Exception as exc:
                last_error = str(exc)
                logger.exception(
                    "Comment execution attempt failed",
                    extra={"post_id": post_id, "attempt": attempt},
                )

                if attempt < self.max_attempts:
                    await asyncio.sleep(self.retry_delay_seconds)

        logger.error(
            "Comment execution failed after retries",
            extra={"post_id": post_id, "attempts": self.max_attempts},
        )
        return {
            "status": "skipped",
            "message": last_error or "Execution failed",
        }

    async def _execute_once(self, post_id: str, comment: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single attempt in the currently configured mode."""

        comment_text = str(comment["text"]).strip()
        persona = comment.get("persona")

        if self.simulation_mode:
            return await self.execution_service.simulate_post_comment(
                post_id=post_id,
                comment_text=comment_text,
                persona=persona if isinstance(persona, dict) else None,
            )

        # TODO: integrate the real posting flow when external execution is enabled.
        raise RuntimeError("Live comment posting is not enabled")

    def _validate_comment(self, post_id: str, comment: Dict[str, Any]) -> str | None:
        """Validate the structure of the execution payload."""

        if not isinstance(post_id, str) or not post_id.strip():
            return "Invalid post_id"
        if not isinstance(comment, dict):
            return "Comment must be a dictionary"

        text = comment.get("text")
        style = comment.get("style")
        confidence = comment.get("confidence")

        if not isinstance(text, str) or not text.strip():
            return "Comment text is required"
        if not isinstance(style, str) or not style.strip():
            return "Comment style is required"
        if confidence is None:
            return "Comment confidence is required"
        if not self._is_valid_confidence(confidence):
            return "Comment confidence must be a number between 0 and 1"

        return None

    def _is_valid_confidence(self, value: Any) -> bool:
        """Check whether a confidence value is usable."""

        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return False

        return 0.0 <= numeric_value <= 1.0
