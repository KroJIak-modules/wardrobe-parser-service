from dataclasses import dataclass
from app.adapters.contracts import AdapterProductDraft, SiteAdapter, SourceContext, Strategy, StrategyContext
from app.adapters.registry import AdapterRegistry
from app.core.exceptions import ConfigError
from app.repositories.source_repository import SourceRecord
from app.services.config_validation_service import ConfigValidationService
from app.services.source_run_service import SourceRunService
from app.strategies.registry import StrategyRegistry


@dataclass
class FakeSourceRepo:
    record: SourceRecord

    def get_by_key(self, source_key: str) -> SourceRecord:
        if source_key != self.record.key:
            raise KeyError(source_key)
        return self.record


class FakeAdapter(SiteAdapter):
    adapter_key = 'jadedldn__v1'
    allowed_strategies = ('s1', 's2', 's3')

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        raw = context.source_config.get('visible_catalog_set', [])
        return [str(x) for x in raw]

    def normalize_product(self, raw_product: dict) -> AdapterProductDraft:
        variants = raw_product.get('variants') if isinstance(raw_product.get('variants'), list) else []
        normalized_variants: list[dict] = []
        if not bool(raw_product.get('force_no_variants')):
            if not variants:
                variants = [
                    {
                        'title': 'Default',
                        'price': raw_product.get('price'),
                        'currency': raw_product.get('currency') or 'USD',
                        'available': True,
                    }
                ]
            for variant in variants:
                normalized_variants.append(
                    {
                        'id': str(variant.get('id') or '').strip() or None,
                        'title': str(variant.get('title') or '').strip() or None,
                        'sku': str(variant.get('sku') or '').strip() or None,
                        'price_amount': variant.get('price_amount', variant.get('price')),
                        'currency_code': str(variant.get('currency_code') or variant.get('currency') or raw_product.get('currency') or 'USD').strip() or None,
                        'available': bool(variant.get('available', True)),
                    }
                )
        return {
            'url': str(raw_product.get('url') or '').strip(),
            'handle': str(raw_product.get('handle') or '').strip() or str(raw_product.get('url') or '').strip(),
            'title': str(raw_product.get('title') or '').strip() or 'Untitled',
            'description_html': str(raw_product.get('description_html') or raw_product.get('description') or '').strip() or None,
            'vendor': str(raw_product.get('vendor') or '').strip() or None,
            'product_type': str(raw_product.get('product_type') or '').strip() or None,
            'tags': raw_product.get('tags') if isinstance(raw_product.get('tags'), list) else [],
            'weight_grams': raw_product.get('weight_grams'),
            'images': [str(x).strip() for x in (raw_product.get('images') or []) if str(x).strip()],
            'variants': normalized_variants,
        }

    def validate_product(self, normalized_product: AdapterProductDraft) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if not normalized_product.get('url'):
            reasons.append('missing_url')
        variants = normalized_product.get('variants') if isinstance(normalized_product.get('variants'), list) else []
        if not any(variant.get('price_amount') for variant in variants):
            reasons.append('missing_price')
        if not any(variant.get('currency_code') for variant in variants):
            reasons.append('missing_currency')
        if not variants:
            reasons.append('missing_variants')
        return (len(reasons) == 0, reasons)


class PayloadStrategy(Strategy):
    def __init__(self, name: str):
        self.name = name

    def run(self, context: StrategyContext) -> list[dict]:
        payloads = context.source.source_config['strategy_payloads']
        out: list[dict] = []
        for item in list(payloads.get(self.name, [])):
            raw = dict(item)
            if not bool(raw.get('force_no_variants')):
                variants = raw.get('variants') if isinstance(raw.get('variants'), list) else []
                if not variants:
                    raw['variants'] = [
                        {
                            'id': 'v1',
                            'title': 'Default',
                            'price': raw.get('price'),
                            'currency': raw.get('currency') or 'USD',
                            'available': True,
                        }
                    ]
            if context.candidate_only and str(raw.get('url') or '').strip() not in context.candidate_urls:
                continue
            out.append(raw)
        return out


class ErrorStrategy(Strategy):
    def __init__(self, name: str):
        self.name = name

    def run(self, context: StrategyContext) -> list[dict]:
        raise RuntimeError(f'boom-{self.name}')


def _build_service(config: dict, *, error_strategies: set[str] | None = None) -> SourceRunService:
    record = SourceRecord(
        id=1,
        key='jadedldn.com',
        url='https://jadedldn.com/',
        adapter_key='jadedldn__v1',
        enabled=True,
        sync_enabled=True,
        config=config,
    )
    repo = FakeSourceRepo(record)

    adapters = AdapterRegistry()
    adapters.register(FakeAdapter())

    strategies = StrategyRegistry()
    error_set = error_strategies or set()
    for name in ('s1', 's2', 's3'):
        if name in error_set:
            strategies.register(ErrorStrategy(name))
        else:
            strategies.register(PayloadStrategy(name))

    return SourceRunService(repo, adapters, strategies)


def _base_config() -> dict:
    return {
        'strategy_sequence': ['s1', 's2', 's3'],
        'retry_limits': {'s1': 0, 's2': 0, 's3': 0},
        'timeouts': {'product_sec': 10, 'source_run_sec': 100},
        'visible_catalog_set': ['u1', 'u2'],
        'strategy_payloads': {'s1': [], 's2': [], 's3': []},
    }


def test_normal_path_success() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'price': 10, 'currency': 'USD', 'weight_grams': 500},
        {'url': 'u2', 'price': 20, 'currency': 'USD', 'weight_grams': 600},
    ]
    svc = _build_service(cfg)

    report: SourceRunReport = svc.run('jadedldn.com', dry_run=False)

    assert report.visible_coverage == 1.0
    assert report.status.value == 'success'


def test_intentional_fallback_success() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = []
    cfg['strategy_payloads']['s2'] = [
        {'url': 'u1', 'price': 10, 'currency': 'USD', 'weight_grams': 500},
        {'url': 'u2', 'price': 20, 'currency': 'USD', 'weight_grams': 600},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com')

    assert report.status.value == 'success'
    assert report.attempts[0].parsed_count == 0
    assert report.attempts[1].parsed_count == 2


def test_final_fallback_success() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = []
    cfg['strategy_payloads']['s2'] = []
    cfg['strategy_payloads']['s3'] = [
        {'url': 'u1', 'price': 10, 'currency': 'USD', 'weight_grams': 500},
        {'url': 'u2', 'price': 20, 'currency': 'USD', 'weight_grams': 600},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com')

    assert report.status.value == 'success'
    assert report.attempts[2].parsed_count == 2


def test_partial_run() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'price': 10, 'currency': 'USD', 'weight_grams': 500},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com')

    assert 0 < report.visible_coverage < 1
    assert report.status.value == 'partial'


def test_failed_run() -> None:
    cfg = _base_config()
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com')

    assert report.visible_coverage == 0
    assert report.status.value == 'failed'


def test_dry_run_sets_flag() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'price': 10, 'currency': 'USD', 'weight_grams': 500},
        {'url': 'u2', 'price': 20, 'currency': 'USD', 'weight_grams': 600},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com', dry_run=True)

    assert report.dry_run is True
    assert report.status.value == 'success'


def test_config_validation_fails_without_strategy_sequence() -> None:
    cfg = _base_config()
    del cfg['strategy_sequence']
    svc = _build_service(cfg)

    try:
        svc.run('jadedldn.com')
        assert False, 'expected ConfigError'
    except ConfigError:
        assert True


def test_config_validation_requires_shopify_js_workers() -> None:
    cfg = _base_config()
    cfg['strategy_sequence'] = ['shopify_js']
    try:
        ConfigValidationService.require_strategy_settings(cfg, ['shopify_js'])
        assert False, 'expected ConfigError'
    except ConfigError:
        assert True


def test_config_validation_rejects_too_large_sitemap_max_products() -> None:
    cfg = _base_config()
    cfg['shopify_sitemap'] = {
        'max_products': 50001,
        'include_locale_sitemaps': False,
        'request_retries': 1,
    }
    try:
        ConfigValidationService.require_strategy_settings(cfg, ['shopify_json'])
        assert False, 'expected ConfigError'
    except ConfigError:
        assert True


def test_config_validation_rejects_invalid_json_js_enrichment_field() -> None:
    cfg = _base_config()
    cfg['shopify_sitemap'] = {
        'max_products': 50000,
        'include_locale_sitemaps': False,
        'request_retries': 1,
    }
    cfg['shopify_market'] = {
        'preferred_currencies': ['USD', 'EUR', 'GBP'],
    }
    cfg['shopify_json_quality'] = {
        'antibot_pause_sec': 3,
        'retry_backoff_sec': [1, 3],
        'enrich_from_js_fields': ['price', 'inventory'],
    }
    try:
        ConfigValidationService.require_strategy_settings(cfg, ['shopify_json'])
        assert False, 'expected ConfigError'
    except ConfigError:
        assert True


def test_config_validation_ignores_unsupported_currency_codes_if_any_valid_left() -> None:
    cfg = _base_config()
    cfg['shopify_sitemap'] = {
        'max_products': 50000,
        'include_locale_sitemaps': False,
        'request_retries': 1,
    }
    cfg['shopify_market'] = {
        'preferred_currencies': ['JPY', 'USD', 'ABC'],
    }
    cfg['shopify_json_quality'] = {
        'antibot_pause_sec': 3,
        'retry_backoff_sec': [1, 3],
        'enrich_from_js_fields': ['price'],
    }
    ConfigValidationService.require_strategy_settings(cfg, ['shopify_json'])


def test_config_validation_accepts_shopify_catalog_page_interval() -> None:
    cfg = _base_config()
    cfg['shopify_sitemap'] = {
        'max_products': 50000,
        'include_locale_sitemaps': False,
        'request_retries': 1,
    }
    cfg['shopify_market'] = {'preferred_currencies': ['USD']}
    cfg['shopify_json_quality'] = {
        'antibot_pause_sec': 3,
        'retry_backoff_sec': [1, 3],
        'page_interval_sec': 0.2,
        'enrich_from_js_fields': [],
    }

    ConfigValidationService.require_strategy_settings(cfg, ['shopify_json'])


def test_config_validation_rejects_currency_priority_without_any_supported_code() -> None:
    cfg = _base_config()
    cfg['shopify_sitemap'] = {
        'max_products': 50000,
        'include_locale_sitemaps': False,
        'request_retries': 1,
    }
    cfg['shopify_market'] = {
        'preferred_currencies': ['JPY', 'ABC'],
    }
    try:
        ConfigValidationService.require_strategy_settings(cfg, ['shopify_json'])
        assert False, 'expected ConfigError'
    except ConfigError:
        assert True


def test_exact_duplicate_listing_is_ignored_without_quarantine_artifacts() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'price': 10, 'currency': 'USD', 'weight_grams': 500, 'handle': 'h1'},
        {'url': 'u1', 'price': 11, 'currency': 'USD', 'weight_grams': 510, 'handle': 'h2'},
        {'url': 'u2', 'price': 20, 'currency': 'USD', 'weight_grams': 600, 'handle': 'h3'},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com')

    assert report.total_found_products == 3
    assert report.total_valid_products == 2
    assert report.errors == []


def test_baseline_visible_coverage_uses_visible_set_only() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'price': 10, 'currency': 'USD', 'weight_grams': 500},
        {'url': 'u2', 'price': 20, 'currency': 'USD', 'weight_grams': 600},
        {'url': 'u3', 'price': 30, 'currency': 'USD', 'weight_grams': 700},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com')

    assert report.visible_catalog_products == 2
    assert report.parsed_visible_products == 2
    assert report.visible_coverage == 1.0


def test_missing_source_weight_does_not_make_product_unavailable() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'title': 'Black hoodie', 'price': 10, 'currency': 'USD', 'weight_grams': 0},
        {'url': 'u2', 'title': 'Blue tee', 'price': 20, 'currency': 'USD', 'weight_grams': 0},
    ]
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.total_valid_products == 2
    assert len(report.unavailable_products) == 0
    assert report.aggregated_status_reasons.get('missing_weight') is None


def test_source_weight_is_preserved_separately_from_service_status() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'title': 'Heavy hoodie', 'price': 10, 'currency': 'USD', 'weight_grams': 820},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com')

    assert report.total_valid_products == 1
    product = report.valid_products[0]
    assert product.get('source_weight_grams') == 820
    assert product.get('weight_source') == 'source'


def test_visible_coverage_uses_handle_when_hosts_differ() -> None:
    cfg = _base_config()
    cfg['visible_catalog_set'] = [
        'https://www.jadedldn.com/products/u1',
        'https://www.jadedldn.com/products/u2',
    ]
    cfg['strategy_payloads']['s1'] = [
        {'url': 'https://jadedldn.com/products/u1', 'handle': 'u1', 'price': 10, 'currency': 'USD', 'weight_grams': 500},
        {'url': 'https://jadedldn.com/products/u2', 'handle': 'u2', 'price': 20, 'currency': 'USD', 'weight_grams': 600},
    ]
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.visible_coverage == 1.0
    assert report.parsed_visible_products == 2
    assert report.status.value == 'success'


def test_visible_coverage_decodes_percent_encoded_handles() -> None:
    cfg = _base_config()
    cfg['visible_catalog_set'] = [
        'https://www.racerworldwide.net/products/vibram%C2%AE-desert-boots',
    ]
    cfg['strategy_payloads']['s1'] = [
        {
            'url': 'https://www.racerworldwide.net/products/vibram®-desert-boots',
            'handle': 'vibram®-desert-boots',
            'price': 10,
            'currency': 'USD',
            'weight_grams': 500,
        },
    ]
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.visible_coverage == 1.0
    assert report.parsed_visible_products == 1
    assert report.status.value == 'success'


def test_cross_strategy_duplicates_are_ignored_without_parser_side_dedup() -> None:
    cfg = _base_config()
    cfg['visible_catalog_set'] = ['u1', 'u2']
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'title': 'Black Hoodie', 'vendor': 'BrandX', 'price': 100, 'currency': 'USD', 'weight_grams': 500},
        {'url': 'u2', 'title': ' black   hoodie ', 'vendor': 'brandx', 'price': 101, 'currency': 'USD', 'weight_grams': 500},
    ]
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.total_found_products == 2
    assert report.parsed_visible_products == 2
    assert report.aggregated_status_reasons.get('deduplicated', 0) == 0


def test_description_html_is_normalized_to_readable_plain_text() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {
            'url': 'u1',
            'price': 10,
            'currency': 'USD',
            'weight_grams': 500,
            'description': (
                '<p>The Big Baggy Black jeans feature a distinctive wide cut.</p>'
                '<div><p><strong>Every piece is meticulously made to order.</strong></p>'
                '<p>Feel free to contact us at '
                '<a href="mailto:support@paradoxeparis.com">support@paradoxeparis.com</a>.'
                '</p></div>'
            ),
        },
    ]
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.total_valid_products == 1
    description = str(report.valid_products[0].get('description') or '')
    assert report.valid_products[0].get('description_html')
    assert description
    assert '<p>' not in description and '<div>' not in description
    assert 'The Big Baggy Black jeans feature a distinctive wide cut.' in description
    assert 'Every piece is meticulously made to order.' in description
    assert 'support@paradoxeparis.com' in description
    assert '\n\n' in description


def test_description_markdown_is_normalized_to_plain_text() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {
            'url': 'u1',
            'price': 10,
            'currency': 'USD',
            'weight_grams': 500,
            'description': (
                '# Title\n\n'
                'Some **bold** text.\n\n'
                '- first item\n'
                '- second item\n\n'
                '[Size chart](https://example.com/chart.png)'
            ),
        },
    ]
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.total_valid_products == 1
    description = str(report.valid_products[0].get('description') or '')
    assert report.valid_products[0].get('description_html')
    assert description
    assert '# ' not in description
    assert '**' not in description
    assert '[Size chart]' not in description
    assert 'Some bold text.' in description
    assert '• first item' in description
    assert '• second item' in description
    assert 'Size chart' in description


def test_product_without_variants_is_marked_unavailable() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {
            'url': 'u1',
            'price': 10,
            'currency': 'USD',
            'weight_grams': 500,
            'variants': [],
            'force_no_variants': True,
        },
    ]
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.total_valid_products == 0
    assert len(report.unavailable_products) == 1
    reasons = set(report.unavailable_products[0].get('status_reasons') or [])
    assert 'missing_variants' in reasons


def test_manual_mode_syncs_only_saved_candidates_without_reconciling_catalog() -> None:
    cfg = _base_config()
    cfg['mode'] = 'manual'
    cfg['strategy_payloads']['s1'] = [
        {'url': 'https://example.test/selected', 'price': 10, 'currency': 'USD'},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com', candidate_urls=['https://example.test/selected'])

    assert report.status.value == 'success'
    assert report.reconcile_missing is False
    assert report.visible_catalog_products == 1
    assert [item['url'] for item in report.valid_products] == ['https://example.test/selected']


def test_auto_mode_candidate_refresh_does_not_reconcile_catalog_products() -> None:
    cfg = _base_config()
    cfg['visible_catalog_set'] = ['https://example.test/selected']
    cfg['strategy_payloads']['s1'] = [
        {'url': 'https://example.test/selected', 'price': 10, 'currency': 'USD'},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com', candidate_urls=['https://example.test/selected'], prefer_candidate_urls=True)

    assert report.status.value == 'success'
    assert report.reconcile_missing is False


def test_auto_mode_complete_sync_reconciles_missing_catalog_products() -> None:
    cfg = _base_config()
    cfg['visible_catalog_set'] = ['https://example.test/selected']
    cfg['strategy_payloads']['s1'] = [
        {'url': 'https://example.test/selected', 'price': 10, 'currency': 'USD'},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com')

    assert report.status.value == 'success'
    assert report.reconcile_missing is True


def test_manual_mode_without_candidates_is_success_noop() -> None:
    cfg = _base_config()
    cfg['mode'] = 'manual'
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.status.value == 'success'
    assert report.visible_catalog_products == 0
    assert report.parsed_visible_products == 0
    assert report.visible_coverage == 1.0
    assert report.total_valid_products == 0


def test_run_enriches_product_gender_before_report() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {
            'url': 'u1',
            'price': 10,
            'currency': 'USD',
            'weight_grams': 500,
            'tags': ['women'],
        },
    ]
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.total_valid_products == 1
    assert report.valid_products[0]['gender'] == 'female'
