"""Campaign and pipeline schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    """Schema for campaign creation input."""

    # TODO: add schema fields.
    pass


class CampaignRead(BaseModel):
    """Schema for campaign read output."""

    # TODO: add schema fields.
    pass


class PipelineRequest(BaseModel):
    """Schema for pipeline execution input."""

    account_id: str = Field(min_length=1)
    niche_text: str = Field(min_length=1)
    mock: bool = False


class PipelineResponse(BaseModel):
    """Schema for pipeline execution output."""

    account_id: str
    niche_text: str
    mock: bool
    result_count: int
    results: list[dict[str, Any]]


class PipelineStartResponse(BaseModel):
    """Schema returned when a background pipeline execution is created."""

    status: str
    execution_id: str
    mode: str | None = None


class ExecutionStatusResponse(BaseModel):
    """Schema returned when querying a background execution."""

    execution_id: str
    status: str
    account_id: str
    niche_text: str
    mode: str
    result_count: int
    results: list[dict[str, Any]]
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class ExecutionListItemResponse(BaseModel):
    """Schema returned when listing recent executions for one account."""

    execution_id: str
    status: str
    result_count: int
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
