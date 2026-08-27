from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

from app.services.run_logger import RunLogger
from app.services.shopify_policies import ShopifyPolicyFactory
from app.strategies.shopify_json import ShopifyJsonStrategy


def _quality(cfg: dict | None = None) -> dict:
    return {
        'timeouts': {'product_sec': 1},
        'shopify_json_quality': {
            'antibot_pause_sec': 0,
            'retry_backoff_sec': [],
            'enrich_from_js_fields': [],
            'page_interval_sec': 0,
        },
        **(cfg or {}),
    }


def _page(items: list[dict]) -> list[dict]:
    return items


def _item(item_id: int, handle: str) -> dict:
    return {'id': item_id, 'handle': handle, 'title': handle}


def _run_collection(monkeypatch, pages: list[list[dict]], candidate_urls: tuple[str, ...]) -> tuple[list[dict], int]:
    strategy = ShopifyJsonStrategy()
    calls: list[int] = []

    def fake_fetch(self, base_url, timeout, *, page, **kwargs):
        calls.append(page)
        return pages[page - 1], None

    monkeypatch.setattr(ShopifyJsonStrategy, '_fetch_products_page_with_retry', fake_fetch)
    fail_types: Counter[str] = Counter()
    out, pages_fetched = strategy._collect_base_pages(
        'https://example.test',
        1,
        http_client=SimpleNamespace(),
        quality=ShopifyPolicyFactory.json_quality(_quality()),
        max_products=0,
        storefront_currency='',
        currency_priority=(),
        logger=RunLogger('strategy-candidate-test'),
        fail_types=fail_types,
        candidate_urls=candidate_urls,
    )
    assert not fail_types
    assert calls == list(range(1, pages_fetched + 1))
    return out, pages_fetched


def test_candidate_collection_returns_only_requested_handles(monkeypatch) -> None:
    page_one = [_item(index, f'other-{index}') for index in range(250)]
    page_one[0] = _item(9001, 'candidate-a')
    page_one[1] = _item(9002, 'candidate-b')
    page_two = [_item(index, f'rest-{index}') for index in range(300, 305)]
    page_two.append(_item(9003, 'candidate-c'))

    out, pages_fetched = _run_collection(
        monkeypatch,
        [_page(page_one), _page(page_two)],
        candidate_urls=(
            'https://example.test/products/candidate-a',
            'https://example.test/products/candidate-b',
            'https://example.test/products/candidate-c',
        ),
    )

    assert pages_fetched == 2
    assert {item['handle'] for item in out} == {'candidate-a', 'candidate-b', 'candidate-c'}


def test_candidate_collection_stops_after_full_candidate_cover(monkeypatch) -> None:
    page_one = [_item(index, f'other-{index}') for index in range(250)]
    page_one[0] = _item(9001, 'candidate-a')
    page_one[1] = _item(9002, 'candidate-b')

    out, pages_fetched = _run_collection(
        monkeypatch,
        [_page(page_one), _page([_item(9999, 'never-reached')])],
        candidate_urls=(
            'https://example.test/products/candidate-a',
            'https://example.test/products/candidate-b',
        ),
    )

    assert pages_fetched == 1
    assert {item['handle'] for item in out} == {'candidate-a', 'candidate-b'}


def test_full_catalog_collection_without_candidates_stays_unchanged(monkeypatch) -> None:
    page_one = [_item(index, f'first-{index}') for index in range(250)]
    page_two = [_item(index, f'second-{index}') for index in range(300, 305)]

    out, pages_fetched = _run_collection(monkeypatch, [_page(page_one), _page(page_two)], candidate_urls=())

    assert pages_fetched == 2
    assert len(out) == 255
    assert {item['handle'] for item in out if item['handle'].startswith('first-')} == {f'first-{i}' for i in range(250)}
