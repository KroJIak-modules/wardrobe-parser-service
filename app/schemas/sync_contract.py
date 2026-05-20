from __future__ import annotations

from pydantic import BaseModel, Field


class SyncJobCreateRequest(BaseModel):
    triggered_by: str = "manual"
    dry_run: bool = False
    sources: list[str] = Field(default_factory=list)
    candidate_urls_by_source: dict[str, list[str]] = Field(default_factory=dict)


class SyncJobCreateResponse(BaseModel):
    job_id: str
    status: str
    created_at: str


class SyncJobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    current_source_name: str | None = None
    current_source_index: int = 0
    total_sources: int = 0
    current_strategy: str | None = None
    current_stage: str | None = None
    products_success: int = 0
    products_error: int = 0
    progress_percent: float = 0.0
    can_cancel: bool = False
    error: str | None = None


class SyncEvent(BaseModel):
    event_id: str
    job_id: str
    seq_no: int
    type: str
    ts: str
    payload: dict = Field(default_factory=dict)


class SyncEventsResponse(BaseModel):
    job_id: str
    next_cursor: int
    items: list[SyncEvent] = Field(default_factory=list)
