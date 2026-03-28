"""Utilities for parser job response serialization."""

from __future__ import annotations

from app.models import ParserJob


def build_job_summary_payload(job: ParserJob) -> dict:
    """Build dict payload for detailed job response."""
    return {
        "id": job.id,
        "status": job.status,
        "triggered_by": job.triggered_by,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "total_products": job.total_products,
        "new_products": job.new_products,
        "updated_products": job.updated_products,
        "new_images": job.new_images,
        "error_count": job.error_count,
        "http_429_count": job.http_429_count,
        "http_5xx_count": job.http_5xx_count,
        "source_runs": [
            {
                "id": run.id,
                "source_id": run.source_id,
                "status": run.status,
                "products_discovered": run.products_discovered,
                "products_fetched": run.products_fetched,
                "products_failed": run.products_failed,
                "discovery_mode": run.discovery_mode,
            }
            for run in job.source_runs
        ],
    }
