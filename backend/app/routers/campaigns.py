"""Campaign and pipeline routers."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

import run_pipeline as pipeline_runner
from app.config import get_settings
from app.schemas.campaign import (
    CampaignCreate,
    ExecutionListItemResponse,
    ExecutionStatusResponse,
    PipelineRequest,
    PipelineStartResponse,
)
from app.schemas.common import ApiMessage
from app.services.behavior.execution_tracker import ExecutionLimitExceededError
from app.services.behavior.execution_tracker import ExecutionTracker


router = APIRouter(prefix="/campaigns", tags=["campaigns"])
pipeline_router = APIRouter(tags=["pipeline"])
logger = logging.getLogger(__name__)


@router.post("/", response_model=ApiMessage, status_code=status.HTTP_201_CREATED)
async def create_campaign(payload: CampaignCreate) -> ApiMessage:
    """Create a campaign resource."""

    _ = payload
    return ApiMessage(status="not_implemented", message="Campaign creation is not implemented yet.")


@router.post("/run", response_model=PipelineStartResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_campaign_pipeline(
    payload: PipelineRequest,
    background_tasks: BackgroundTasks,
) -> PipelineStartResponse:
    """Run the campaign pipeline."""

    # TODO: re-enable authentication before production.
    return await _start_pipeline_execution(payload, background_tasks)


@pipeline_router.post("/run", response_model=PipelineStartResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_pipeline(
    payload: PipelineRequest,
    background_tasks: BackgroundTasks,
) -> PipelineStartResponse:
    """Run the engagement pipeline from a top-level endpoint."""

    # TODO: re-enable authentication before production.
    return await _start_pipeline_execution(payload, background_tasks)


@pipeline_router.get("/execution/{execution_id}", response_model=ExecutionStatusResponse)
async def get_execution_status(
    execution_id: str,
) -> ExecutionStatusResponse:
    """Return the status and results for a background execution."""

    # TODO: re-enable authentication before production.
    tracker = await asyncio.to_thread(ExecutionTracker)
    execution = await asyncio.to_thread(tracker.get_execution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found.")

    return ExecutionStatusResponse(**execution)


@pipeline_router.get("/executions", response_model=list[ExecutionListItemResponse])
async def list_executions(
    account_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1),
) -> list[ExecutionListItemResponse]:
    """Return recent executions for one account."""

    # TODO: re-enable authentication before production.
    normalized_account_id = (account_id or "").strip()
    if not normalized_account_id:
        raise HTTPException(status_code=400, detail="account_id is required")

    logger.info(
        "Fetching execution history",
        extra={"account_id": normalized_account_id, "limit": limit},
    )
    tracker = await asyncio.to_thread(ExecutionTracker)
    executions = await asyncio.to_thread(tracker.list_executions, normalized_account_id, limit)
    return [ExecutionListItemResponse(**execution) for execution in executions]


async def _start_pipeline_execution(
    payload: PipelineRequest,
    background_tasks: BackgroundTasks,
) -> PipelineStartResponse:
    """Create and schedule a background pipeline execution."""

    logger.info(
        "Received pipeline execution request",
        extra={
            "account_id": payload.account_id,
            "mock": payload.mock,
        },
    )

    try:
        tracker = await asyncio.to_thread(ExecutionTracker)
        settings = get_settings()
        execution_id = uuid4().hex
        try:
            current_count = await asyncio.to_thread(
                tracker.create_execution_with_limit,
                execution_id,
                payload.account_id,
                payload.niche_text,
                payload.mock,
                settings.pipeline_max_executions_per_day,
            )
        except ExecutionLimitExceededError as exc:
            logger.warning(
                "Rejected pipeline execution due to daily execution limit",
                extra={
                    "account_id": payload.account_id,
                    "current_count": exc.current_count,
                    "daily_limit": exc.limit,
                },
            )
            raise HTTPException(status_code=429, detail="Daily execution limit reached") from exc

        background_tasks.add_task(
            _execute_pipeline_background,
            execution_id,
            payload.account_id,
            payload.niche_text,
            payload.mock,
        )
        logger.info(
            "Accepted pipeline execution within daily limit",
            extra={
                "account_id": payload.account_id,
                "current_count": current_count,
                "daily_limit": max(int(settings.pipeline_max_executions_per_day), 1),
            },
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        logger.exception(
            "Failed to start pipeline execution",
            extra={"account_id": payload.account_id, "mock": payload.mock},
        )
        raise HTTPException(status_code=500, detail="Failed to start pipeline execution.") from exc

    return PipelineStartResponse(
        status="started",
        execution_id=execution_id,
        mode="mock" if payload.mock else "real",
    )


async def _execute_pipeline_background(
    execution_id: str,
    account_id: str,
    niche_text: str,
    mock: bool,
) -> None:
    """Run the pipeline in a background task and persist execution status."""

    tracker = await asyncio.to_thread(ExecutionTracker)
    settings = get_settings()
    timeout_seconds = max(float(settings.pipeline_timeout_seconds), 1.0)
    max_retries = max(int(settings.pipeline_max_retries), 0)
    max_attempts = max_retries + 1
    started_at = monotonic()
    logger.info(
        "Background pipeline execution started",
        extra={
            "execution_id": execution_id,
            "account_id": account_id,
            "mode": "mock" if mock else "real",
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
        },
    )

    try:
        await asyncio.to_thread(tracker.mark_running, execution_id)
        last_error_message = "Pipeline execution failed."
        for attempt in range(1, max_attempts + 1):
            logger.info(
                "Background pipeline execution attempt started",
                extra={
                    "execution_id": execution_id,
                    "account_id": account_id,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "timeout_seconds": timeout_seconds,
                },
            )

            try:
                results = await asyncio.wait_for(
                    pipeline_runner._run_pipeline(
                        account_id=account_id,
                        niche_text=niche_text,
                        use_mock=mock,
                    ),
                    timeout=timeout_seconds,
                )
                await asyncio.to_thread(
                    tracker.update_mode,
                    execution_id,
                    _resolve_execution_mode(mock=mock, results=results),
                )
                await asyncio.to_thread(tracker.mark_completed, execution_id, results)
                logger.info(
                    "Background pipeline execution completed",
                    extra={
                        "execution_id": execution_id,
                        "account_id": account_id,
                        "attempt": attempt,
                        "result_count": len(results),
                        "duration_seconds": round(monotonic() - started_at, 3),
                    },
                )
                return
            except Exception as exc:
                last_error_message = _get_execution_error_message(exc)
                should_retry = attempt < max_attempts and _should_retry_execution(exc)
                log_extra = {
                    "execution_id": execution_id,
                    "account_id": account_id,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "duration_seconds": round(monotonic() - started_at, 3),
                }

                if isinstance(exc, asyncio.TimeoutError):
                    logger.error("Background pipeline execution timed out", extra=log_extra)
                else:
                    logger.exception("Background pipeline execution attempt failed", extra=log_extra)

                if should_retry:
                    logger.warning(
                        "Retrying background pipeline execution",
                        extra={
                            "execution_id": execution_id,
                            "account_id": account_id,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "previous_error": last_error_message,
                        },
                    )
                    continue

                try:
                    await asyncio.to_thread(tracker.mark_failed, execution_id, last_error_message)
                except Exception:
                    logger.exception(
                        "Failed to persist pipeline execution failure",
                        extra={"execution_id": execution_id, "account_id": account_id},
                    )

                logger.error(
                    "Background pipeline execution failed after retries",
                    extra={
                        "execution_id": execution_id,
                        "account_id": account_id,
                        "attempts_used": attempt,
                        "duration_seconds": round(monotonic() - started_at, 3),
                        "final_error": last_error_message,
                    },
                )
                return
    except Exception as exc:
        error_message = _get_execution_error_message(exc)
        try:
            await asyncio.to_thread(tracker.mark_failed, execution_id, error_message)
        except Exception:
            logger.exception(
                "Failed to persist unexpected pipeline control failure",
                extra={"execution_id": execution_id, "account_id": account_id},
            )

        logger.exception(
            "Background pipeline execution encountered an unexpected control failure",
            extra={
                "execution_id": execution_id,
                "account_id": account_id,
                "duration_seconds": round(monotonic() - started_at, 3),
            },
        )


def _should_retry_execution(exc: Exception) -> bool:
    """Return ``True`` when the execution failure looks transient."""

    if isinstance(exc, asyncio.TimeoutError):
        return True
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError, NotImplementedError)):
        return False

    return True


def _get_execution_error_message(exc: Exception) -> str:
    """Return a stable error message for execution tracking."""

    if isinstance(exc, asyncio.TimeoutError):
        return "Execution timed out"

    return str(exc).strip() or "Pipeline execution failed."


def _resolve_execution_mode(mock: bool, results: list[dict[str, object]]) -> str:
    """Resolve one execution mode from pipeline result metadata."""

    if mock:
        return "mock"

    list_mode = getattr(results, "mode", None)
    if isinstance(list_mode, str) and list_mode.strip():
        return list_mode.strip().lower()

    resolved_mode = "real"
    for result in results:
        if not isinstance(result, dict):
            continue
        metadata = result.get("pipeline_metadata", {})
        if not isinstance(metadata, dict):
            continue
        result_mode = str(metadata.get("mode", "")).strip().lower()
        if result_mode == "degraded":
            return "degraded"
        if result_mode == "fallback":
            resolved_mode = "fallback"

    return resolved_mode
