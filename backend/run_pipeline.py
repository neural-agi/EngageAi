"""CLI entry point for the engagement pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

from app.config import get_settings, validate_required_settings
from app.core.memory_store import MemoryStore
from app.observability.logging import configure_logging
from app.orchestrator.runners import MockPipelineRunner, RealPipelineRunner
from app.services.behavior.scheduler_service import SchedulerService


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(description="Run the EngageAI engagement pipeline.")
    parser.add_argument("account_id", help="Account identifier used to load the session.")
    parser.add_argument("niche_text", help="Target niche text used for relevance analysis.")
    parser.add_argument(
        "--persona",
        dest="persona_name",
        default=None,
        help="Optional persona id or name for the pipeline run.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock posts instead of the scraper.",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run the pipeline continuously on a schedule.",
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=30.0,
        help="Base interval between scheduled runs in continuous mode.",
    )
    parser.add_argument(
        "--daily-limit",
        type=int,
        default=20,
        help="Maximum successful executions allowed per day in continuous mode.",
    )
    return parser


async def _run_pipeline(
    account_id: str,
    niche_text: str,
    use_mock: bool = False,
    persona_name: str | None = None,
) -> list[dict[str, Any]]:
    """Execute the pipeline and return the result payload."""

    runner = MockPipelineRunner() if use_mock else RealPipelineRunner()
    logger.info(
        "Selected pipeline execution mode",
        extra={
            "mode": runner.mode,
            "account_id": account_id,
        },
    )
    return await runner.run(
        account_id=account_id,
        niche_text=niche_text,
        persona_name=persona_name,
    )


async def _run_continuous(
    account_id: str,
    niche_text: str,
    use_mock: bool = False,
    persona_name: str | None = None,
    interval_minutes: float = 30.0,
    daily_limit: int = 20,
) -> None:
    """Run the engagement pipeline continuously using the scheduler service."""

    memory_store = MemoryStore(account_id=account_id)
    scheduler = SchedulerService(
        memory_store=memory_store,
        daily_comment_limit=daily_limit,
    )

    await scheduler.run_forever(
        run_once=lambda: _run_pipeline(
            account_id=account_id,
            niche_text=niche_text,
            use_mock=use_mock,
            persona_name=persona_name,
        ),
        interval_minutes=interval_minutes,
    )


def main() -> int:
    """Parse arguments, run the pipeline, and print results."""

    settings = get_settings()
    configure_logging(settings.log_level)
    validate_required_settings(settings)

    parser = build_parser()
    args = parser.parse_args()

    mode = "mock" if args.mock else "real"
    print(
        f"Running pipeline in {mode} mode for "
        f"account_id={args.account_id!r} niche_text={args.niche_text!r}"
    )

    if args.continuous:
        print(
            "Starting continuous mode with "
            f"interval_minutes={args.interval_minutes} daily_limit={args.daily_limit}"
        )
        try:
            asyncio.run(
                _run_continuous(
                    account_id=args.account_id,
                    niche_text=args.niche_text,
                    use_mock=args.mock,
                    persona_name=args.persona_name,
                    interval_minutes=args.interval_minutes,
                    daily_limit=args.daily_limit,
                )
            )
        except KeyboardInterrupt:
            print("Continuous mode stopped.")
        return 0

    results = asyncio.run(
        _run_pipeline(
            args.account_id,
            args.niche_text,
            use_mock=args.mock,
            persona_name=args.persona_name,
        )
    )

    print(f"Completed. Result count: {len(results)}")
    print(json.dumps(results, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
