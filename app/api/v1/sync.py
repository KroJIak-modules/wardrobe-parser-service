from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from urllib.parse import urlparse

from app.core.exceptions import ConfigError
from app.domain.statuses import SourceRunStatus
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
probe_orchestrator = SyncOrchestratorService(max_workers=2)


class SourceFlagPatch(BaseModel):
    enabled: bool | None = None
    sync_enabled: bool | None = None
    requested_currency_priority: list[str] | None = None
    currency_method: str | None = None
    locked_currency: str | None = None


class ProbeProductRequest(BaseModel):
    product_url: str
    dry_run: bool = False


def _normalize_host(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or parsed.netloc or parsed.path or "").strip().lower()
    if host.startswith("www."):
        return host[4:]
    return host


def _source_hosts(source: object) -> set[str]:
    hosts: set[str] = set()
    primary = _normalize_host(str(getattr(source, "url", "") or ""))
    if primary:
        hosts.add(primary)
    cfg = getattr(source, "config", None)
    if isinstance(cfg, dict):
        raw_domains = cfg.get("source_domains")
        if isinstance(raw_domains, list):
            for raw in raw_domains:
                host = _normalize_host(str(raw or "").strip())
                if host:
                    hosts.add(host)
    return hosts


def _normalize_product_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = _normalize_host(url)
    path = (parsed.path or "/").rstrip("/") or "/"
    query = parsed.query.strip()
    return f"{host}{path}?{query}" if query else f"{host}{path}"


def _extract_product_handle(url: str) -> str:
    try:
        parts = [p for p in urlparse(str(url or "").strip()).path.split("/") if p]
    except Exception:
        return ""
    lowered = [p.lower() for p in parts]
    if "products" not in lowered:
        return ""
    idx = lowered.index("products")
    if idx + 1 >= len(parts):
        return ""
    return str(parts[idx + 1] or "").strip().lower()


def _extract_vinted_item_id(url: str) -> str:
    try:
        parts = [p for p in urlparse(str(url or "").strip()).path.split("/") if p]
    except Exception:
        return ""
    lowered = [p.lower() for p in parts]
    if "items" not in lowered:
        return ""
    idx = lowered.index("items")
    if idx + 1 >= len(parts):
        return ""
    raw = str(parts[idx + 1] or "").strip().lower()
    if not raw:
        return ""
    # vinted format: /items/{id}-{slug}
    head = raw.split("-", 1)[0].strip()
    return head if head.isdigit() else ""


def _filter_report_by_product_url(report: SourceRunReport, product_url: str) -> SourceRunReport:
    target = _normalize_product_url(product_url)
    target_host = _normalize_host(product_url)
    target_handle = _extract_product_handle(product_url)
    target_vinted_item_id = _extract_vinted_item_id(product_url)

    def match(item: dict) -> bool:
        if not isinstance(item, dict):
            return False
        raw_url = str(item.get("url") or "").strip()
        if not raw_url:
            return False
        normalized = _normalize_product_url(raw_url)
        if normalized == target:
            return True
        if target_host and _normalize_host(raw_url) != target_host:
            return False
        if target_handle:
            return _extract_product_handle(raw_url) == target_handle
        if target_vinted_item_id:
            return _extract_vinted_item_id(raw_url) == target_vinted_item_id
        return False

    valid = [x for x in (report.valid_products or []) if match(x)]
    unavailable = [x for x in (report.unavailable_products or []) if match(x)]
    combined = valid + unavailable
    attempts = list(report.attempts or [])
    if attempts:
        last = attempts[-1]
        attempts[-1] = last.model_copy(update={"raw_count": len(combined), "parsed_count": len(valid)})
    status_value = SourceRunStatus.SUCCESS if valid else (SourceRunStatus.PARTIAL if unavailable else SourceRunStatus.FAILED)
    return report.model_copy(
        update={
            "status": status_value,
            "valid_products": valid,
            "unavailable_products": unavailable,
            "top_valid_products": valid[:10],
            "total_found_products": len(combined),
            "total_valid_products": len(valid),
            "parsed_visible_products": len(valid),
            "visible_catalog_products": 1 if combined else 0,
            "visible_coverage": 1.0 if valid else 0.0,
            "attempts": attempts,
            "errors": [] if (valid or unavailable) else [f"product_not_found:{product_url}"],
        }
    )


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
            'config': dict(item.config or {}),
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
            currency_method=payload.currency_method,
            locked_currency=payload.locked_currency,
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
    candidate_urls_by_source: dict[str, list[str]] = {}
    raw_candidates = payload.candidate_urls_by_source if isinstance(payload.candidate_urls_by_source, dict) else {}
    for raw_key, raw_urls in raw_candidates.items():
        key = str(raw_key or "").strip()
        if not key or key not in source_keys:
            continue
        if not isinstance(raw_urls, list):
            continue
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_url in raw_urls:
            url = str(raw_url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            normalized.append(url)
        candidate_urls_by_source[key] = normalized

    try:
        job = sync_orchestrator.create_job(
            source_keys=source_keys,
            source_candidate_urls=candidate_urls_by_source,
            dry_run=bool(payload.dry_run),
            runner=lambda source_key, dry_run, run_id, candidate_urls: svc.run(
                source_key=source_key,
                dry_run=dry_run,
                run_id=run_id,
                candidate_urls=candidate_urls,
                prefer_candidate_urls=bool(candidate_urls),
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SyncJobCreateResponse(
        job_id=job.job_id,
        status=job.status,
        created_at=job.created_at.isoformat(),
    )


@router.post('/probe/jobs', response_model=SyncJobCreateResponse, status_code=status.HTTP_201_CREATED)
def create_probe_product_job(payload: ProbeProductRequest) -> SyncJobCreateResponse:
    product_url = str(payload.product_url or "").strip()
    if not product_url:
        raise HTTPException(status_code=400, detail="product_url is required")
    svc = service_factory.build()
    sources = svc.source_repo.list_all()
    target_host = _normalize_host(product_url)
    matched_source_key: str | None = None
    for src in sources:
        src_hosts = _source_hosts(src)
        if target_host and target_host in src_hosts:
            matched_source_key = src.key
            break
    if not matched_source_key:
        raise HTTPException(status_code=400, detail=f"source for host not found: {target_host}")
    try:
        job = probe_orchestrator.create_job(
            source_keys=[matched_source_key],
            source_candidate_urls={matched_source_key: [product_url]},
            dry_run=bool(payload.dry_run),
            runner=lambda source_key, dry_run, run_id, candidate_urls: _filter_report_by_product_url(
                svc.run(
                    source_key=source_key,
                    dry_run=dry_run,
                    run_id=run_id,
                    candidate_urls=candidate_urls,
                    prefer_candidate_urls=True,
                ),
                product_url,
            ),
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
    progress = float(getattr(job, "current_progress_percent", 0.0) or 0.0)
    if progress <= 0.0:
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
    progress = float(getattr(job, "current_progress_percent", 0.0) or 0.0)
    if progress <= 0.0:
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


@router.get('/probe/jobs/latest', response_model=SyncJobStatusResponse | None)
def get_latest_probe_job() -> SyncJobStatusResponse | None:
    job = probe_orchestrator.get_latest()
    if job is None:
        return None
    total = max(1, len(job.source_keys))
    progress = float(getattr(job, "current_progress_percent", 0.0) or 0.0)
    if progress <= 0.0:
        progress = min(100.0, max(0.0, (job.processed_sources / total) * 100.0))
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


@router.get('/probe/jobs/{job_id}', response_model=SyncJobStatusResponse)
def get_probe_job_status(job_id: str) -> SyncJobStatusResponse:
    job = probe_orchestrator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f'job not found: {job_id}')
    total = max(1, len(job.source_keys))
    progress = float(getattr(job, "current_progress_percent", 0.0) or 0.0)
    if progress <= 0.0:
        progress = min(100.0, max(0.0, (job.processed_sources / total) * 100.0))
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


@router.get('/probe/jobs/{job_id}/events', response_model=SyncEventsResponse)
def get_probe_job_events(job_id: str, cursor: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500)) -> SyncEventsResponse:
    job = probe_orchestrator.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f'job not found: {job_id}')
    events, next_cursor = probe_orchestrator.get_events(job_id=job_id, cursor=cursor, limit=limit)
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


@router.post('/probe/jobs/{job_id}/cancel', response_model=SyncJobStatusResponse)
def cancel_probe_job(job_id: str) -> SyncJobStatusResponse:
    job = probe_orchestrator.cancel(job_id)
    total = max(1, len(job.source_keys))
    progress = float(getattr(job, "current_progress_percent", 0.0) or 0.0)
    if progress <= 0.0:
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
