from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.core.exceptions import ConfigError
from app.schemas.run_report import SourceRunReport
from app.schemas.sync_contract import (
    SyncEvent,
    SyncEventsResponse,
    SyncJobCreateRequest,
    SyncJobCreateResponse,
    SyncJobStatusResponse,
)
from app.services.source_run_service_factory import SourceRunServiceFactory
from app.services.sync_orchestrator_service import SyncOrchestratorService

router = APIRouter(prefix='/sync', tags=['sync'])
service_factory = SourceRunServiceFactory()
sync_orchestrator = SyncOrchestratorService(max_workers=1)


class SourceFlagPatch(BaseModel):
    enabled: bool | None = None
    sync_enabled: bool | None = None
    requested_currency_priority: list[str] | None = None


@router.get('/sources')
def list_sources() -> list[dict]:
    svc = service_factory.build()
    items = svc.source_repo.list_all()
    return [
        {
            'id': item.id,
            'key': item.key,
            'url': item.url,
            'adapter_key': item.adapter_key,
            'enabled': item.enabled,
            'sync_enabled': item.sync_enabled,
        }
        for item in items
    ]


@router.patch('/sources/{source_key}')
def patch_source(source_key: str, payload: SourceFlagPatch) -> dict:
    svc = service_factory.build()
    try:
        updated = svc.source_repo.patch_flags(
            source_key,
            enabled=payload.enabled,
            sync_enabled=payload.sync_enabled,
            requested_currency_priority=payload.requested_currency_priority,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        'id': updated.id,
        'key': updated.key,
        'url': updated.url,
        'adapter_key': updated.adapter_key,
        'enabled': updated.enabled,
        'sync_enabled': updated.sync_enabled,
    }


@router.post('/sources/{source_key}/run', response_model=SourceRunReport)
def run_source(source_key: str, dry_run: bool = Query(default=False)) -> SourceRunReport:
    svc = service_factory.build()
    try:
        return svc.run(source_key=source_key, dry_run=dry_run)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/jobs', response_model=SyncJobCreateResponse, status_code=status.HTTP_201_CREATED)
def create_sync_job(payload: SyncJobCreateRequest) -> SyncJobCreateResponse:
    svc = service_factory.build()
    items = svc.source_repo.list_all()
    enabled = [it for it in items if bool(it.enabled) and bool(it.sync_enabled)]
    all_sources = {str(it.key).strip().lower(): str(it.key).strip() for it in items}
    allowed_enabled = {str(it.key).strip().lower(): str(it.key).strip() for it in enabled}
    requested = [str(s).strip() for s in (payload.sources or []) if str(s).strip()]
    if requested:
        normalized = [s.lower() for s in requested]
        # Explicit per-source launch is allowed regardless of source enabled/sync_enabled flags.
        source_keys = [all_sources[s] for s in normalized if s in all_sources]
    else:
        source_keys = [str(it.key).strip() for it in enabled]
    if not source_keys:
        if requested:
            raise HTTPException(status_code=400, detail='requested sources not found')
        if not allowed_enabled:
            raise HTTPException(status_code=400, detail='no sync-enabled sources')
        raise HTTPException(status_code=400, detail='no eligible sources')
    try:
        job = sync_orchestrator.create_job(
            source_keys=source_keys,
            dry_run=bool(payload.dry_run),
            runner=lambda source_key, dry_run, run_id: svc.run(source_key=source_key, dry_run=dry_run, run_id=run_id),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SyncJobCreateResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at.isoformat(),
    )


@router.get('/jobs/latest', response_model=SyncJobStatusResponse | None)
def get_latest_sync_job() -> SyncJobStatusResponse | None:
    job = sync_orchestrator.get_latest()
    if job is None:
        return None
    total = max(1, len(job.source_keys))
    progress = min(100.0, max(0.0, (job.processed_sources / total) * 100.0))
    if job.status in {'completed', 'failed', 'cancelled'}:
        progress = 100.0
    stage = job.current_stage
    return SyncJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        current_source_name=job.current_source_name,
        current_source_index=job.current_source_index,
        total_sources=len(job.source_keys),
        current_strategy=job.current_strategy,
        current_stage=stage,
        products_success=job.products_success,
        products_error=job.products_error,
        progress_percent=progress,
        can_cancel=job.status in {'queued', 'in_progress'},
        error=job.error,
    )


@router.get('/jobs/{job_id}/events', response_model=SyncEventsResponse)
def get_sync_job_events(job_id: str, cursor: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500)) -> SyncEventsResponse:
    job = sync_orchestrator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f'job not found: {job_id}')
    events, next_cursor = sync_orchestrator.get_events(job_id=job_id, cursor=cursor, limit=limit)
    return SyncEventsResponse(
        job_id=job_id,
        next_cursor=next_cursor,
        items=[
            SyncEvent(
                event_id=e.event_id,
                job_id=e.job_id,
                seq_no=e.seq_no,
                type=e.type,
                ts=e.ts.isoformat(),
                payload=e.payload,
            )
            for e in events
        ],
    )


@router.get('/jobs/{job_id}', response_model=SyncJobStatusResponse)
def get_sync_job_status(job_id: str) -> SyncJobStatusResponse:
    job = sync_orchestrator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f'job not found: {job_id}')
    total = max(1, len(job.source_keys))
    progress = min(100.0, max(0.0, (job.processed_sources / total) * 100.0))
    if job.status in {'completed', 'failed', 'cancelled'}:
        progress = 100.0
    stage = job.current_stage
    return SyncJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        current_source_name=job.current_source_name,
        current_source_index=job.current_source_index,
        total_sources=len(job.source_keys),
        current_strategy=job.current_strategy,
        current_stage=stage,
        products_success=job.products_success,
        products_error=job.products_error,
        progress_percent=progress,
        can_cancel=job.status in {'queued', 'in_progress'},
        error=job.error,
    )


@router.post('/jobs/{job_id}/cancel', response_model=SyncJobStatusResponse)
def cancel_sync_job(job_id: str) -> SyncJobStatusResponse:
    job = sync_orchestrator.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f'job not found: {job_id}')
    total = max(1, len(job.source_keys))
    progress = min(100.0, max(0.0, (job.current_source_index / total) * 100.0))
    if job.status in {'completed', 'failed', 'cancelled'}:
        progress = 100.0
    return SyncJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        current_source_name=job.current_source_name,
        current_source_index=job.current_source_index,
        total_sources=len(job.source_keys),
        current_strategy=job.current_strategy,
        current_stage=job.current_stage,
        products_success=job.products_success,
        products_error=job.products_error,
        progress_percent=progress,
        can_cancel=job.status in {'queued', 'in_progress'},
        error=job.error,
    )
