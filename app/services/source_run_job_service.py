from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Callable
from uuid import uuid4

from app.domain.statuses import SourceRunStatus
from app.schemas.run_report import SourceRunReport


@dataclass
class SourceRunJob:
    job_id: str
    source_key: str
    dry_run: bool
    status: SourceRunStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    report: SourceRunReport | None = None


@dataclass
class SourceRunJobCreatedResult:
    job: SourceRunJob
    is_new: bool


class SourceRunJobService:
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, SourceRunJob] = {}
        self._futures: dict[str, Future[None]] = {}
        self._active_by_source: dict[str, str] = {}
        self._lock = Lock()
        self._stale_pending_sec = 180

    def create(self, source_key: str, dry_run: bool, runner: Callable[[str], SourceRunReport]) -> SourceRunJobCreatedResult:
        now = datetime.now(timezone.utc)
        job = SourceRunJob(
            job_id=str(uuid4()),
            source_key=source_key,
            dry_run=dry_run,
            status=SourceRunStatus.PENDING,
            created_at=now,
        )
        with self._lock:
            active_job_id = self._active_by_source.get(source_key)
            if active_job_id:
                active = self._jobs.get(active_job_id)
                if active and active.status in {SourceRunStatus.PENDING, SourceRunStatus.IN_PROGRESS}:
                    if (
                        active.status == SourceRunStatus.PENDING
                        and (now - active.created_at).total_seconds() > self._stale_pending_sec
                    ):
                        self._futures.pop(active_job_id, None)
                        self._jobs.pop(active_job_id, None)
                        self._active_by_source.pop(source_key, None)
                    else:
                        return SourceRunJobCreatedResult(job=active, is_new=False)
            self._jobs[job.job_id] = job
            self._active_by_source[source_key] = job.job_id
        future = self._executor.submit(self._execute, job.job_id, runner)
        with self._lock:
            self._futures[job.job_id] = future
        return SourceRunJobCreatedResult(job=job, is_new=True)

    def get(self, job_id: str) -> SourceRunJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {SourceRunStatus.SUCCESS, SourceRunStatus.PARTIAL, SourceRunStatus.FAILED, SourceRunStatus.CANCELLED}:
                self._futures.pop(job_id, None)
                self._jobs.pop(job_id, None)
            return job

    def cancel(self, job_id: str) -> SourceRunJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status in {SourceRunStatus.SUCCESS, SourceRunStatus.PARTIAL, SourceRunStatus.FAILED, SourceRunStatus.CANCELLED}:
                return job
            if job.status == SourceRunStatus.IN_PROGRESS:
                raise RuntimeError(f'job already in progress and cannot be cancelled safely: {job_id}')
            future = self._futures.get(job_id)
            if future and future.cancel():
                job.status = SourceRunStatus.CANCELLED
                job.finished_at = datetime.now(timezone.utc)
                if self._active_by_source.get(job.source_key) == job_id:
                    self._active_by_source.pop(job.source_key, None)
            else:
                raise RuntimeError(f'job cannot be cancelled: {job_id}')
            return job

    def _execute(self, job_id: str, runner: Callable[[str], SourceRunReport]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.status == SourceRunStatus.CANCELLED:
                return
            job.status = SourceRunStatus.IN_PROGRESS
            job.started_at = datetime.now(timezone.utc)
        try:
            report = runner(job_id)
            with self._lock:
                job = self._jobs[job_id]
                job.report = report
                job.status = report.status
                job.finished_at = datetime.now(timezone.utc)
                if self._active_by_source.get(job.source_key) == job_id:
                    self._active_by_source.pop(job.source_key, None)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                job = self._jobs[job_id]
                job.error = str(exc)
                job.status = SourceRunStatus.FAILED
                job.finished_at = datetime.now(timezone.utc)
                if self._active_by_source.get(job.source_key) == job_id:
                    self._active_by_source.pop(job.source_key, None)
