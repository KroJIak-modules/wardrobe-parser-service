"""Progress callback factories for parser sync worker execution."""

from __future__ import annotations

from typing import Callable

from app.services.parser_sync.progress_tracker import job_progress_tracker


def build_source_sync_progress_callbacks(job_id: str) -> dict[str, Callable]:
    """Build and return progress callbacks used by source sync executor."""

    def on_source_discovered(total_products_in_source: int) -> None:
        job_progress_tracker.set_current_source_expected_products(
            job_id=job_id,
            total_products=total_products_in_source,
        )

    def on_product_processed(
        product_title: str | None,
        processed_in_source: int,
        _total_in_source: int,
    ) -> None:
        job_progress_tracker.mark_product_processed(
            job_id=job_id,
            product_title=product_title,
            processed_in_current_source=processed_in_source,
        )

    def on_discovery_progress() -> None:
        job_progress_tracker.mark_discovery_progress(job_id=job_id)

    def on_discovery_detail_progress(event: dict) -> None:
        stage = str(event.get("stage") or "").strip()
        if stage:
            job_progress_tracker.set_current_stage(job_id=job_id, stage=stage)

        products_total_raw = event.get("products_total")
        if products_total_raw is not None:
            try:
                job_progress_tracker.set_current_source_expected_products_absolute(
                    job_id=job_id,
                    total_products=int(products_total_raw),
                )
            except (TypeError, ValueError):
                pass

        products_processed_raw = event.get("products_processed")
        if products_processed_raw is not None:
            try:
                job_progress_tracker.set_current_source_processed_products_absolute(
                    job_id=job_id,
                    processed_products=int(products_processed_raw),
                )
            except (TypeError, ValueError):
                pass

    return {
        "on_source_discovered": on_source_discovered,
        "on_product_processed": on_product_processed,
        "on_discovery_progress": on_discovery_progress,
        "on_discovery_detail_progress": on_discovery_detail_progress,
    }

