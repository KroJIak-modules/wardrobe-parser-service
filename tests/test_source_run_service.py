from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.adapters.contracts import SiteAdapter, SourceContext, Strategy, StrategyContext
from app.adapters.registry import AdapterRegistry
from app.core.exceptions import ConfigError
from app.repositories.source_repository import SourceRecord
from app.schemas.run_report import SourceRunReport
from app.services.config_validation_service import ConfigValidationService
from app.services.source_run_service import SourceRunService
from app.services.weight_rules_client import WeightRule, WeightRulesPayload
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

    def normalize_product(self, raw_product: dict) -> dict:
        return dict(raw_product)

    def validate_product(self, normalized_product: dict) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if not normalized_product.get('url'):
            reasons.append('missing_url')
        if not normalized_product.get('price'):
            reasons.append('missing_price')
        if not normalized_product.get('currency'):
            reasons.append('missing_currency')
        if normalized_product.get('weight_grams') is None:
            reasons.append('missing_weight')
        return (len(reasons) == 0, reasons)


class PayloadStrategy(Strategy):
    def __init__(self, name: str):
        self.name = name

    def run(self, context: StrategyContext) -> list[dict]:
        payloads = context.source.source_config['strategy_payloads']
        return list(payloads.get(self.name, []))


class ErrorStrategy(Strategy):
    def __init__(self, name: str):
        self.name = name

    def run(self, context: StrategyContext) -> list[dict]:
        raise RuntimeError(f'boom-{self.name}')


class FakeWeightRulesClient:
    def __init__(self, rules: list[WeightRule]) -> None:
        self._rules = rules

    def fetch(self) -> WeightRulesPayload:
        return WeightRulesPayload(revision='test', rules=self._rules)


class FakeBackendContractWeightRulesClient:
    """Imitates backend contract payload conversion path."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def fetch(self) -> WeightRulesPayload:
        revision = str(self.payload.get('revision') or 'unknown')
        out: list[WeightRule] = []
        for item in self.payload.get('rules') or []:
            weight = int(item.get('weight_grams') or 0)
            keywords = [str(x).strip().lower() for x in (item.get('keywords') or []) if str(x).strip()]
            if weight > 0:
                out.append(WeightRule(weight_grams=weight, keywords=keywords))
        return WeightRulesPayload(revision=revision, rules=out)


class FakeReportService:
    def __init__(self) -> None:
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / 'report.md'

    def write(self, report: SourceRunReport) -> Path:
        self.path.write_text('test report\n', encoding='utf-8')
        return self.path


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

    return SourceRunService(repo, adapters, strategies, markdown_report_service=FakeReportService())


def _build_service_with_rules(config: dict, rules: list[WeightRule]) -> SourceRunService:
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
    for name in ('s1', 's2', 's3'):
        strategies.register(PayloadStrategy(name))
    return SourceRunService(
        repo,
        adapters,
        strategies,
        markdown_report_service=FakeReportService(),
        weight_rules_client=FakeWeightRulesClient(rules),
    )


def _build_service_with_backend_contract(config: dict, payload: dict) -> SourceRunService:
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
    for name in ('s1', 's2', 's3'):
        strategies.register(PayloadStrategy(name))
    return SourceRunService(
        repo,
        adapters,
        strategies,
        markdown_report_service=FakeReportService(),
        weight_rules_client=FakeBackendContractWeightRulesClient(payload),
    )


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
    cfg['shopify_currency'] = {
        'requested_currency_priority': ['USD', 'EUR', 'GBP'],
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
    cfg['shopify_currency'] = {
        'requested_currency_priority': ['JPY', 'USD', 'ABC'],
    }
    ConfigValidationService.require_strategy_settings(cfg, ['shopify_json'])


def test_config_validation_rejects_currency_priority_without_any_supported_code() -> None:
    cfg = _base_config()
    cfg['shopify_sitemap'] = {
        'max_products': 50000,
        'include_locale_sitemaps': False,
        'request_retries': 1,
    }
    cfg['shopify_currency'] = {
        'requested_currency_priority': ['JPY', 'ABC'],
    }
    try:
        ConfigValidationService.require_strategy_settings(cfg, ['shopify_json'])
        assert False, 'expected ConfigError'
    except ConfigError:
        assert True


def test_duplicate_policy_marks_error() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'price': 10, 'currency': 'USD', 'weight_grams': 500, 'handle': 'h1'},
        {'url': 'u1', 'price': 11, 'currency': 'USD', 'weight_grams': 510, 'handle': 'h2'},
        {'url': 'u2', 'price': 20, 'currency': 'USD', 'weight_grams': 600, 'handle': 'h3'},
    ]
    svc = _build_service(cfg)

    report = svc.run('jadedldn.com')

    assert any('duplicate_url:u1' in e for e in report.errors)
    assert 'u1' in report.quarantined_urls


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


def test_keyword_weight_rule_makes_product_valid() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'title': 'Black hoodie', 'price': 10, 'currency': 'USD', 'weight_grams': 0},
        {'url': 'u2', 'title': 'Blue tee', 'price': 20, 'currency': 'USD', 'weight_grams': 0},
    ]
    rules = [WeightRule(weight_grams=700, keywords=['hoodie'])]
    svc = _build_service_with_rules(cfg, rules)
    report = svc.run('jadedldn.com')
    assert report.status.value in {'partial', 'success'}
    assert report.total_valid_products >= 1


def test_backend_contract_rules_are_applied_in_service_pipeline() -> None:
    cfg = _base_config()
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'title': 'Black hoodie', 'price': 10, 'currency': 'USD', 'weight_grams': 0},
    ]
    payload = {
        'revision': 'abc123',
        'rules': [
            {'weight_grams': 700, 'keywords': ['hoodie']},
            {'weight_grams': 0, 'keywords': ['bad']},
        ],
    }
    svc = _build_service_with_backend_contract(cfg, payload)
    report = svc.run('jadedldn.com')
    assert report.total_valid_products == 1
    assert report.weight_source_stats.get('keyword_rule', 0) >= 1


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


def test_dedup_scoring_filters_title_vendor_price_duplicates() -> None:
    cfg = _base_config()
    cfg['visible_catalog_set'] = ['u1', 'u2']
    cfg['dedup'] = {'enabled': True, 'score_threshold': 0.75}
    cfg['strategy_payloads']['s1'] = [
        {'url': 'u1', 'title': 'Black Hoodie', 'vendor': 'BrandX', 'price': 100, 'currency': 'USD', 'weight_grams': 500},
        {'url': 'u2', 'title': ' black   hoodie ', 'vendor': 'brandx', 'price': 101, 'currency': 'USD', 'weight_grams': 500},
    ]
    svc = _build_service(cfg)
    report = svc.run('jadedldn.com')
    assert report.total_found_products == 2
    assert report.parsed_visible_products == 1
    assert report.aggregated_unavailable_reasons.get('deduplicated', 0) == 1
    assert any(e.startswith('dedup_candidate:') for e in report.errors)


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
    assert description
    assert '# ' not in description
    assert '**' not in description
    assert '[Size chart]' not in description
    assert 'Some bold text.' in description
    assert '• first item' in description
    assert '• second item' in description
    assert 'Size chart' in description
