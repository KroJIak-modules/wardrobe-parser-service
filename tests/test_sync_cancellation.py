from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace

from app.adapters.contracts import StrategyContext
from app.services.run_logger import RunLogger
from app.services.shopify_policies import ShopifyPolicyFactory
from app.services.source_run_service import SourceRunService
from app.services.sync_orchestrator_service import RuntimeJob, SyncOrchestratorService
from app.schemas.run_report import SourceRunReport
from app.schemas.source_product import SourceProductDraft
from app.domain.statuses import SourceRunStatus
from app.strategies.shopify_json import ShopifyJsonStrategy


def _item(item_id: int, handle: str) -> dict:
    return {'id': item_id, 'handle': handle, 'title': handle}


def test_shopify_json_feed_stops_when_cancelled_midway(monkeypatch) -> None:
    strategy = ShopifyJsonStrategy()
    pages = [
        [_item(1, 'a'), _item(2, 'b')],
        [_item(3, 'c'), _item(4, 'd')],
        [_item(5, 'e'), _item(6, 'f')],
    ]
    fetched_pages: list[int] = []

    def fake_fetch(self, base_url, timeout, *, page, **kwargs):
        fetched_pages.append(page)
        return pages[page - 1], None

    monkeypatch.setattr(ShopifyJsonStrategy, '_fetch_products_page_with_retry', fake_fetch)
    seen = {'cancelled': False}

    def should_cancel() -> bool:
        return seen['cancelled'] or len(fetched_pages) >= 1

    out, pages_fetched = strategy._collect_base_pages(
        'https://example.test',
        1,
        http_client=SimpleNamespace(),
        quality=ShopifyPolicyFactory.json_quality({
            'shopify_json_quality': {
                'antibot_pause_sec': 0,
                'retry_backoff_sec': [],
                'enrich_from_js_fields': [],
                'page_interval_sec': 0,
            },
        }),
        max_products=0,
        storefront_currency='',
        currency_priority=(),
        logger=RunLogger('cancel-feed-test'),
        fail_types=Counter(),
        should_cancel=should_cancel,
    )

    assert fetched_pages == [1]
    assert pages_fetched == 1
    assert [item['handle'] for item in out] == ['a', 'b']


def test_source_run_skips_strategies_and_reports_partial_when_cancelled() -> None:
    from test_source_run_service import _base_config, _build_service, PayloadStrategy

    cfg = _base_config()
    cfg['mode'] = 'manual'
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'title': 'A', 'price': 10, 'currency': 'USD', 'weight_grams': 100},
    ]
    svc = _build_service(cfg)

    calls = {'count': 0}
    original_run = PayloadStrategy.run

    def counting_run(self, context: StrategyContext) -> list[dict]:
        calls['count'] += 1
        return original_run(self, context)

    PayloadStrategy.run = counting_run
    try:
        report = svc.run('jadedldn.com', candidate_urls=['u1'], cancel_check=lambda: True)
    finally:
        PayloadStrategy.run = original_run

    assert calls['count'] == 0
    assert report.status == SourceRunStatus.PARTIAL
    assert report.valid_products == []
    assert report.reconcile_missing is False


def test_orchestrator_drops_batch_and_finalizes_canceled_mid_source() -> None:
    svc = SyncOrchestratorService(max_workers=1)
    job = RuntimeJob(
        job_id='job-cancel-mid-source',
        status='queued',
        created_at=datetime.now(timezone.utc),
        dry_run=False,
        source_keys=['demo-source', 'second-source'],
    )
    svc._jobs[job.job_id] = job
    svc._active_job_id = job.job_id

    def runner(source_key: str, dry_run: bool, run_id: str, candidate_urls: list[str], should_cancel=None) -> SourceRunReport:
        if should_cancel is not None:
            should_cancel()
        report = SourceRunReport(
            source_key=source_key,
            adapter_key='demo-adapter',
            status=SourceRunStatus.SUCCESS,
            valid_products=[SourceProductDraft(url=f'https://demo.example/products/{source_key}', title=source_key, variants=[])],
        )
        if source_key == 'demo-source':
            with svc._lock:
                svc._jobs['job-cancel-mid-source'].cancel_requested = True
        return report

    svc._execute(job.job_id, runner)

    with svc._lock:
        final_job = svc._jobs['job-cancel-mid-source']
        event_types = [event.type for event in final_job.events]

    assert final_job.status == 'canceled'
    assert 'product_batch' not in event_types
    assert final_job.processed_sources == 0
    assert final_job.current_source_key in {None, 'demo-source'}
