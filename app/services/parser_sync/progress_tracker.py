"""In-memory tracker for live parser sync progress details."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional


@dataclass(slots=True)
class JobProgressState:
    """Mutable live progress snapshot for one running job."""

    job_id: str
    total_sources: int = 0
    current_source_name: Optional[str] = None
    current_source_index: int = 0
    current_stage: str = "idle"
    current_source_total_products: int = 0
    current_source_processed_products: int = 0
    processed_products_total: int = 0
    expected_products_total: int = 0
    current_product_title: Optional[str] = None
    discovery_ticks: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ParserJobProgressTracker:
    """Thread-safe storage for live sync progress snapshots."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._states: dict[str, JobProgressState] = {}

    def start_job(self, *, job_id: str, total_sources: int) -> None:
        with self._lock:
            self._states[job_id] = JobProgressState(
                job_id=job_id,
                total_sources=total_sources,
                updated_at=datetime.now(timezone.utc),
            )

    def start_source(self, *, job_id: str, source_name: str, source_index: int) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if not state:
                return
            state.current_source_name = source_name
            state.current_source_index = source_index
            state.current_stage = "discovering_urls"
            state.current_source_total_products = 0
            state.current_source_processed_products = 0
            state.current_product_title = None
            state.discovery_ticks = 0
            state.updated_at = datetime.now(timezone.utc)

    def mark_discovery_progress(self, *, job_id: str) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if not state:
                return
            # Keep this lightweight: each tick means parser is alive and moving.
            state.discovery_ticks += 1
            state.current_stage = "discovering_urls"
            state.updated_at = datetime.now(timezone.utc)

    def set_current_source_expected_products(self, *, job_id: str, total_products: int) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if not state:
                return
            safe_total = max(int(total_products), 0)
            state.current_source_total_products = safe_total
            state.expected_products_total += safe_total
            state.current_stage = "syncing_products"
            state.updated_at = datetime.now(timezone.utc)

    def set_current_source_expected_products_absolute(self, *, job_id: str, total_products: int) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if not state:
                return
            safe_total = max(int(total_products), 0)
            previous_total = max(int(state.current_source_total_products), 0)
            state.current_source_total_products = safe_total
            state.expected_products_total = max(
                int(state.expected_products_total) + (safe_total - previous_total),
                0,
            )
            state.updated_at = datetime.now(timezone.utc)

    def set_current_source_processed_products_absolute(
        self,
        *,
        job_id: str,
        processed_products: int,
        product_title: Optional[str] = None,
    ) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if not state:
                return
            safe_processed = max(int(processed_products), 0)
            previous_processed = max(int(state.current_source_processed_products), 0)
            state.current_source_processed_products = safe_processed
            state.processed_products_total = max(
                int(state.processed_products_total) + (safe_processed - previous_processed),
                0,
            )
            state.current_product_title = (product_title or "").strip() or state.current_product_title
            state.updated_at = datetime.now(timezone.utc)

    def set_current_stage(self, *, job_id: str, stage: str) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if not state:
                return
            normalized_stage = str(stage or "").strip()
            if normalized_stage:
                state.current_stage = normalized_stage
                state.updated_at = datetime.now(timezone.utc)

    def mark_product_processed(
        self,
        *,
        job_id: str,
        product_title: Optional[str],
        processed_in_current_source: int,
    ) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if not state:
                return
            state.current_product_title = (product_title or "").strip() or None
            state.current_source_processed_products = max(int(processed_in_current_source), 0)
            state.processed_products_total += 1
            state.current_stage = "syncing_products"
            state.updated_at = datetime.now(timezone.utc)

    def finish_source(self, *, job_id: str) -> None:
        with self._lock:
            state = self._states.get(job_id)
            if not state:
                return
            state.current_product_title = None
            state.current_stage = "source_finished"
            state.updated_at = datetime.now(timezone.utc)

    def finish_job(self, *, job_id: str) -> None:
        with self._lock:
            self._states.pop(job_id, None)

    def get(self, *, job_id: str) -> Optional[JobProgressState]:
        with self._lock:
            state = self._states.get(job_id)
            if not state:
                return None
            return JobProgressState(
                job_id=state.job_id,
                total_sources=state.total_sources,
                current_source_name=state.current_source_name,
                current_source_index=state.current_source_index,
                current_stage=state.current_stage,
                current_source_total_products=state.current_source_total_products,
                current_source_processed_products=state.current_source_processed_products,
                processed_products_total=state.processed_products_total,
                expected_products_total=state.expected_products_total,
                current_product_title=state.current_product_title,
                discovery_ticks=state.discovery_ticks,
                updated_at=state.updated_at,
            )


job_progress_tracker = ParserJobProgressTracker()
