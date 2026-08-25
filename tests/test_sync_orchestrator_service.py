from datetime import datetime, timezone

from app.domain.statuses import SourceRunStatus
from app.schemas.run_report import SourceRunReport, StrategyAttempt
from app.schemas.sync_stages import SyncStageCode
from app.services.sync_orchestrator_service import RuntimeJob, SyncOrchestratorService


def test_build_product_batch_items_keeps_valid_products_without_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "variants": [],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["variants"] == []


def test_build_product_batch_items_keeps_valid_products_with_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert len(items[0]["variants"]) == 1
    assert items[0]["gender"] == "unisex"


def test_build_product_batch_items_keeps_unavailable_missing_weight_without_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[],
        unavailable_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "variants": [],
                "status": "unavailable",
                "status_reasons": ["missing_weight"],
            }
        ],
    )
    assert len(items) == 1
    assert items[0]["status_reasons"] == ["missing_weight"]


def test_build_product_batch_items_keeps_unavailable_missing_weight_with_variants() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[],
        unavailable_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": False}
                ],
                "status": "unavailable",
                "status_reasons": ["missing_weight"],
            }
        ],
    )
    assert len(items) == 1
    assert len(items[0]["variants"]) == 1


def test_build_product_batch_items_preserves_gender() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "gender": "female",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["gender"] == "female"


def test_build_product_batch_items_emits_designer_category_and_nullable_status_reason() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "designer": "Rick Owens",
                "category": "Outerwear",
                "status_reason": "missing_weight",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["designer"] == "Rick Owens"
    assert items[0]["category"] == "Outerwear"
    assert items[0]["status_reason"] == "missing_weight"


def test_build_product_batch_items_emits_normalized_tags() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "tags": "active_test, runway ,active_test",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["tags"] == ["active_test", "runway"]


def test_build_product_batch_items_emits_source_weight_only() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "source_weight_grams": 820,
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["source_weight_grams"] == 820
    assert "weight_grams" not in items[0]


def test_build_product_batch_items_sets_null_status_reason_when_absent() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "handle": "a",
                "title": "A",
                "description": "A",
                "designer": "Rick Owens",
                "category": "Outerwear",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["status_reason"] is None


def test_build_product_batch_items_emits_product_source_ref() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    items = svc._build_product_batch_items(
        valid_products=[
            {
                "url": "https://demo.com/products/a",
                "source_ref": {
                    "external_id": "ext-123",
                },
                "handle": "a",
                "title": "A",
                "description": "A",
                "designer": "Rick Owens",
                "category": "Outerwear",
                "variants": [
                    {"id": "v1", "title": "One", "price_amount": 100, "currency_code": "USD", "available": True}
                ],
                "status": "available",
            }
        ],
        unavailable_products=[],
    )
    assert len(items) == 1
    assert items[0]["source_ref"] == {
        "external_id": "ext-123",
    }


def test_execute_emits_report_error_details_in_source_finished_payload() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    job = RuntimeJob(
        job_id="job-report-error",
        status="queued",
        created_at=datetime.now(timezone.utc),
        dry_run=False,
        source_keys=["demo-source"],
    )
    svc._jobs[job.job_id] = job
    svc._active_job_id = job.job_id

    def runner(source_key: str, dry_run: bool, run_id: str, candidate_urls: list[str]) -> SourceRunReport:
        assert source_key == "demo-source"
        assert dry_run is False
        assert candidate_urls == []
        assert run_id
        return SourceRunReport(
            source_key=source_key,
            adapter_key="demo-adapter",
            status=SourceRunStatus.FAILED,
            errors=["s1: boom-s1"],
            attempts=[StrategyAttempt(strategy="s1", success=False, error="boom-s1")],
        )

    svc._execute(job.job_id, runner)

    event = next(evt for evt in job.events if evt.type == "source_finished")
    assert event.payload["stage_code"] == SyncStageCode.SOURCE_FAILED.value
    assert event.payload["error_code"] == "source_failed"
    assert event.payload["error_message"] == "boom-s1"
    assert event.payload["error"] == {
        "status": "failed",
        "report_errors": ["s1: boom-s1"],
        "attempt_errors": [
            {
                "strategy": "s1",
                "error": "boom-s1",
            }
        ],
    }


def test_execute_uses_source_run_reconciliation_decision() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    job = RuntimeJob(
        job_id="job-manual-catalog",
        status="queued",
        created_at=datetime.now(timezone.utc),
        dry_run=False,
        source_keys=["demo-source"],
    )
    svc._jobs[job.job_id] = job
    svc._active_job_id = job.job_id

    def runner(source_key: str, dry_run: bool, run_id: str, candidate_urls: list[str]) -> SourceRunReport:
        return SourceRunReport(
            source_key=source_key,
            adapter_key="demo-adapter",
            status=SourceRunStatus.SUCCESS,
            reconcile_missing=False,
            valid_products=[{"url": "https://demo.example/products/a", "title": "A", "variants": []}],
        )

    svc._execute(job.job_id, runner)

    event = next(evt for evt in job.events if evt.type == "product_batch")
    assert event.payload["reconcile_missing"] is False


def test_execute_marks_product_batch_incomplete_for_partial_source_response() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    job = RuntimeJob(
        job_id="job-partial-catalog",
        status="queued",
        created_at=datetime.now(timezone.utc),
        dry_run=False,
        source_keys=["demo-source"],
    )
    svc._jobs[job.job_id] = job
    svc._active_job_id = job.job_id

    def runner(source_key: str, dry_run: bool, run_id: str, candidate_urls: list[str]) -> SourceRunReport:
        return SourceRunReport(
            source_key=source_key,
            adapter_key="demo-adapter",
            status=SourceRunStatus.PARTIAL,
            valid_products=[{"url": "https://demo.example/products/a", "title": "A", "variants": []}],
        )

    svc._execute(job.job_id, runner)

    event = next(evt for evt in job.events if evt.type == "product_batch")
    assert event.payload["reconcile_missing"] is False


def test_execute_emits_exception_error_details_in_source_finished_payload() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    job = RuntimeJob(
        job_id="job-exception-error",
        status="queued",
        created_at=datetime.now(timezone.utc),
        dry_run=False,
        source_keys=["demo-source"],
    )
    svc._jobs[job.job_id] = job
    svc._active_job_id = job.job_id

    def runner(source_key: str, dry_run: bool, run_id: str, candidate_urls: list[str]) -> SourceRunReport:
        raise RuntimeError("hard fail")

    svc._execute(job.job_id, runner)

    event = next(evt for evt in job.events if evt.type == "source_finished")
    assert event.payload["stage_code"] == SyncStageCode.SOURCE_FAILED.value
    assert event.payload["error_code"] == "RuntimeError"
    assert event.payload["error_message"] == "hard fail"
    assert event.payload["error"] == {
        "type": "RuntimeError",
        "message": "hard fail",
    }
