"""Scheduling service for continuous pipeline execution."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from app.core.memory_store import MemoryStore


logger = logging.getLogger(__name__)


class SchedulerService:
    """Run the engagement pipeline continuously with human-like timing variation."""

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        interval_jitter_ratio: float = 0.2,
        daily_comment_limit: int = 20,
        inactivity_probability: float = 0.2,
        rng: random.Random | None = None,
    ) -> None:
        """Initialize scheduler settings and persistence helpers."""

        self.memory_store = memory_store or MemoryStore()
        self.interval_jitter_ratio = max(0.0, interval_jitter_ratio)
        self.daily_comment_limit = max(1, daily_comment_limit)
        self.inactivity_probability = min(max(0.0, inactivity_probability), 1.0)
        self._rng = rng or random.Random()

    async def run_forever(
        self,
        run_once: Callable[[], Awaitable[list[dict[str, Any]]]],
        interval_minutes: float,
    ) -> None:
        """Run a pipeline callable continuously using a jittered schedule."""

        normalized_interval_minutes = max(0.1, interval_minutes)

        while True:
            if self._daily_limit_reached():
                logger.info(
                    "Skipping scheduled run because the daily comment limit was reached",
                    extra={"daily_comment_limit": self.daily_comment_limit},
                )
            elif self._should_skip_for_inactivity():
                logger.info("Skipping scheduled run to simulate human inactivity")
            else:
                await self._execute_scheduled_run(run_once)

            sleep_seconds = self._next_interval_seconds(normalized_interval_minutes)
            logger.info(
                "Sleeping until the next scheduled run",
                extra={"sleep_seconds": round(sleep_seconds, 2)},
            )
            await asyncio.sleep(sleep_seconds)

    async def _execute_scheduled_run(
        self,
        run_once: Callable[[], Awaitable[list[dict[str, Any]]]],
    ) -> None:
        """Execute one scheduled pipeline cycle and persist the completion timestamp."""

        logger.info(
            "Starting scheduled pipeline run",
            extra={"last_run_timestamp": self.memory_store.get_last_run_timestamp()},
        )

        try:
            results = await run_once()
        except Exception:
            logger.exception("Scheduled pipeline run failed")
            return

        completed_timestamp = self._timestamp()
        self.memory_store.set_last_run_timestamp(completed_timestamp)
        successful_executions = sum(
            1
            for result in results
            if isinstance(result, dict)
            and isinstance(result.get("execution"), dict)
            and result["execution"].get("status") == "success"
        )

        logger.info(
            "Scheduled pipeline run completed",
            extra={
                "completed_timestamp": completed_timestamp,
                "result_count": len(results),
                "successful_executions": successful_executions,
            },
        )

    def _daily_limit_reached(self) -> bool:
        """Check whether the daily execution quota has been exhausted."""

        return self.memory_store.count_executions_for_day() >= self.daily_comment_limit

    def _should_skip_for_inactivity(self) -> bool:
        """Randomly skip a run to simulate human inactivity."""

        return self._rng.random() < self.inactivity_probability

    def _next_interval_seconds(self, interval_minutes: float) -> float:
        """Return the next sleep interval in seconds with jitter applied."""

        base_seconds = max(1.0, interval_minutes * 60.0)
        jitter_ratio = self._rng.uniform(
            1.0 - self.interval_jitter_ratio,
            1.0 + self.interval_jitter_ratio,
        )
        return max(1.0, base_seconds * jitter_ratio)

    def _timestamp(self) -> str:
        """Return the scheduler timestamp in ISO format."""

        return datetime.now(timezone.utc).isoformat()
