from fastapi import APIRouter, HTTPException, Query, status

from app.core.exceptions import ConfigError
from app.schemas.run_report import SourceRunJobCreated, SourceRunJobStatus, SourceRunReport
from app.services.source_run_job_service import SourceRunJobService
from app.services.source_run_service_factory import SourceRunServiceFactory

router = APIRouter(prefix='/sync', tags=['sync'])
job_service = SourceRunJobService(max_workers=2)
service_factory = SourceRunServiceFactory()


@router.post('/sources/{source_key}/run', response_model=SourceRunReport)
def run_source(source_key: str, dry_run: bool = Query(default=False)) -> SourceRunReport:
    svc = service_factory.build()
    try:
        return svc.run(source_key=source_key, dry_run=dry_run)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/sources/{source_key}/run-async', response_model=SourceRunJobCreated, status_code=status.HTTP_202_ACCEPTED)
def run_source_async(source_key: str, dry_run: bool = Query(default=False)) -> SourceRunJobCreated:
    svc = service_factory.build()
    try:
        svc.require_runnable_source(source_key)
        created = job_service.create(
            source_key=source_key,
            dry_run=dry_run,
            runner=lambda job_id: svc.run(source_key=source_key, dry_run=dry_run, run_id=job_id),
        )
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    job = created.job
    return SourceRunJobCreated(
        job_id=job.job_id,
        source_key=job.source_key,
        dry_run=job.dry_run,
        status=job.status,
        created_at=job.created_at.isoformat(),
    )


@router.get('/jobs/{job_id}', response_model=SourceRunJobStatus)
def get_job_status(job_id: str) -> SourceRunJobStatus:
    job = job_service.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f'job not found: {job_id}')
    return SourceRunJobStatus(
        job_id=job.job_id,
        source_key=job.source_key,
        dry_run=job.dry_run,
        status=job.status,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        error=job.error,
        report=job.report,
    )


@router.post('/jobs/{job_id}/cancel', response_model=SourceRunJobStatus)
def cancel_job(job_id: str) -> SourceRunJobStatus:
    try:
        job = job_service.cancel(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail=f'job not found: {job_id}')
    return SourceRunJobStatus(
        job_id=job.job_id,
        source_key=job.source_key,
        dry_run=job.dry_run,
        status=job.status,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        error=job.error,
        report=job.report,
    )
