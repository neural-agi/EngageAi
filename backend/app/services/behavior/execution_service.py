"""Execution simulation service for comment actions."""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any

from app.core.memory_store import MemoryStore


logger = logging.getLogger(__name__)


class ExecutionService:
    """Simulate comment execution and persist execution history."""

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        delay_range_seconds: tuple[float, float] = (2.0, 10.0),
        rng: random.Random | None = None,
    ) -> None:
        """Initialize the simulation service."""

        self.memory_store = memory_store or MemoryStore()
        minimum_delay, maximum_delay = delay_range_seconds
        self.minimum_delay = max(0.0, minimum_delay)
        self.maximum_delay = max(self.minimum_delay, maximum_delay)
        self._rng = rng or random.Random()

    async def simulate_post_comment(
        self,
        post_id: str,
        comment_text: str,
        persona: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Simulate posting a comment and record the execution history."""

        normalized_post_id = post_id.strip()
        normalized_comment_text = comment_text.strip()
        persona = persona or {}
        persona_name = str(persona.get("name", "Unknown persona")).strip() or "Unknown persona"

        if self.memory_store.has_execution_for_post(normalized_post_id):
            logger.info(
                "Skipping duplicate simulated execution",
                extra={"post_id": normalized_post_id, "persona": persona_name},
            )
            return {
                "status": "duplicate",
                "message": "Execution already recorded for this post.",
                "post_id": normalized_post_id,
                "comment_text": normalized_comment_text,
                "persona": persona_name,
                "timestamp": self._timestamp(),
            }

        await asyncio.sleep(self._rng.uniform(self.minimum_delay, self.maximum_delay))

        record = {
            "post_id": normalized_post_id,
            "comment_text": normalized_comment_text,
            "persona": persona_name,
            "timestamp": self._timestamp(),
        }
        self.memory_store.remember_execution(record)

        logger.info(
            "Simulated comment execution",
            extra={
                "post_id": record["post_id"],
                "comment_text": record["comment_text"],
                "persona": record["persona"],
                "timestamp": record["timestamp"],
            },
        )

        return {
            "status": "success",
            "message": "Comment simulated successfully.",
            **record,
        }

    def _timestamp(self) -> str:
        """Return an ISO timestamp for execution records."""

        return datetime.now(timezone.utc).isoformat()
