from app.services.shopify_currency_resolver import ShopifyCurrencyResolver


def test_resolver_extracts_shopify_active_currency() -> None:
    html = '<script>Shopify.currency = {"active":"EUR","rate":"1.0"};</script>'
    assert ShopifyCurrencyResolver._extract_candidates(html)[0] == ('EUR', 'shopify_currency_active')


def test_resolver_normalizes_gbr_to_gbp() -> None:
    assert ShopifyCurrencyResolver.normalize('gbr') == 'GBP'


def test_resolve_currency_uses_storefront_currency_without_usd_fallback() -> None:
    from app.strategies.shopify_json import ShopifyJsonStrategy

    assert ShopifyJsonStrategy._resolve_currency(None, 'EUR', ('EUR', 'USD', 'GBP')) == 'EUR'
    assert ShopifyJsonStrategy._resolve_currency(None, '', ('EUR', 'USD', 'GBP')) == ''
    assert ShopifyJsonStrategy._resolve_currency('CAD', 'CAD', ('EUR', 'USD', 'GBP')) == ''


def test_currency_policy_preferred_currencies_are_normalized() -> None:
    from app.services.shopify_policies import ShopifyPolicyFactory

    policy = ShopifyPolicyFactory.currency({
        'shopify_market': {
            'preferred_currencies': ['gbr', 'usd'],
        }
    })
    assert policy.preferred_currencies[0] == 'GBP'


def test_currency_policy_filters_unsupported_codes() -> None:
    from app.services.shopify_policies import ShopifyPolicyFactory

    policy = ShopifyPolicyFactory.currency({
        'shopify_market': {
            'preferred_currencies': ['JPY', 'usd', 'ZZZ', 'gbr'],
        }
    })
    assert policy.preferred_currencies == ('JPY', 'USD', 'GBP')


def test_currency_policy_fixed_ambient_mode() -> None:
    from app.services.shopify_policies import ShopifyPolicyFactory

    policy = ShopifyPolicyFactory.currency({
        'shopify_market': {
            'request_mode': 'fixed_ambient',
            'fixed_currency': 'eur',
            'preferred_currencies': ['USD', 'EUR', 'GBP'],
        }
    })
    assert policy.request_mode == 'fixed_ambient'
    assert policy.fixed_currency == 'EUR'


def test_currency_policy_fixed_param_mode() -> None:
    from app.services.shopify_policies import ShopifyPolicyFactory

    policy = ShopifyPolicyFactory.currency({
        'shopify_market': {
            'request_mode': 'fixed_param',
            'fixed_currency': 'gbr',
            'preferred_currencies': ['USD', 'EUR', 'GBP'],
        }
    })
    assert policy.request_mode == 'fixed_param'
    assert policy.fixed_currency == 'GBP'


def test_shopify_js_weight_accepts_weight_field() -> None:
    from app.strategies.shopify_js import ShopifyJsStrategy

    assert ShopifyJsStrategy._best_variant_weight([
        {'title': 'S', 'weight': 310},
        {'title': 'M', 'weight': 315},
    ]) == 310


def test_shopify_json_mapping_preserves_source_published_at() -> None:
    from collections import Counter

    from app.services.shopify_policies import ShopifyJsonQualityPolicy
    from app.strategies.shopify_json import ShopifyJsonStrategy

    mapped = ShopifyJsonStrategy._map_product(
        {
            'handle': 'belt-denim-hood-dress',
            'title': 'BELT DENIM HOOD DRESS',
            'published_at': '2023-04-07T23:20:24+02:00',
            'variants': [{'price': '100', 'grams': 500}],
            'images': [],
            'tags': [],
        },
        'https://nofaithstudios.com',
        1,
        quality=ShopifyJsonQualityPolicy(
            antibot_pause_sec=0,
            retry_backoff_sec=(),
            enrich_from_js_fields=frozenset(),
            page_interval_sec=0,
        ),
        allowed_currencies=('USD',),
        storefront_currency='USD',
        fail_types=Counter(),
    )

    assert mapped['published_at'] == '2023-04-07T23:20:24+02:00'


def test_shopify_json_mapping_does_not_fetch_product_page_for_missing_category(monkeypatch) -> None:
    from collections import Counter

    from app.services.shopify_policies import ShopifyJsonQualityPolicy
    from app.strategies.shopify_json import ShopifyJsonStrategy

    def unexpected_page_fetch(*_args, **_kwargs):
        raise AssertionError('catalog mapping must not fetch a product page')

    monkeypatch.setattr(
        'app.services.shopify_catalog_metadata_service.ShopifyCatalogMetadataService._resolve_html_category',
        unexpected_page_fetch,
    )

    mapped = ShopifyJsonStrategy._map_product(
        {
            'handle': 'belt-denim-hood-dress',
            'title': 'BELT DENIM HOOD DRESS',
            'published_at': '2023-04-07T23:20:24+02:00',
            'variants': [{'price': '100', 'grams': 500}],
            'images': [],
            'tags': [],
        },
        'https://nofaithstudios.com',
        1,
        quality=ShopifyJsonQualityPolicy(
            antibot_pause_sec=0,
            retry_backoff_sec=(),
            enrich_from_js_fields=frozenset(),
            page_interval_sec=0,
        ),
        allowed_currencies=('USD',),
        storefront_currency='USD',
        fail_types=Counter(),
    )

    assert mapped['category'] is None


def test_shopify_json_retries_a_throttled_catalog_page_without_js_fallback(monkeypatch) -> None:
    from app.services.shopify_policies import ShopifyJsonQualityPolicy
    from app.strategies.shopify_json import ShopifyJsonStrategy

    strategy = ShopifyJsonStrategy()
    responses = iter([
        (None, 'antibot'),
        (None, 'antibot'),
        ([{'id': 1, 'handle': 'recovered'}], None),
    ])
    calls: list[dict] = []
    sleeps: list[float] = []

    def fetch_page(*_args, **kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(strategy, '_fetch_products_page', fetch_page)
    monkeypatch.setattr('app.strategies.shopify_json.time.sleep', sleeps.append)

    items, state = strategy._fetch_products_page_with_retry(
        'https://example.com',
        10,
        http_client=object(),
        page=3,
        storefront_currency='USD',
        currency_priority=('USD',),
        quality=ShopifyJsonQualityPolicy(
            antibot_pause_sec=3,
            retry_backoff_sec=(1, 7),
            enrich_from_js_fields=(),
            page_interval_sec=0,
        ),
    )

    assert items == [{'id': 1, 'handle': 'recovered'}]
    assert state is None
    assert len(calls) == 3
    assert sleeps == [3, 7]


def test_shopify_js_mapping_preserves_source_published_at(monkeypatch) -> None:
    from app.strategies.shopify_js import ShopifyJsStrategy

    payload = {
        'title': 'BELT DENIM HOOD DRESS',
        'published_at': '2023-04-07T23:20:24+02:00',
        'variants': [{'price': 10000, 'weight': 500}],
        'images': [],
        'tags': [],
    }

    response = type('Response', (), {'status_code': 200, 'payload': payload})()
    monkeypatch.setattr('app.strategies.shopify_js.ShopifyHttpClient.get_json', lambda *_args, **_kwargs: response)
    monkeypatch.setattr('app.strategies.shopify_js.ShopifyCatalogMetadataService.resolve_category', lambda *_args, **_kwargs: None)

    mapped = ShopifyJsStrategy._parse_product_js(
        'https://nofaithstudios.com',
        'https://nofaithstudios.com/products/belt-denim-hood-dress',
        1,
        allowed_currencies=('USD',),
        currency_priority=('USD',),
        storefront_currency='USD',
        fixed_country='',
    )

    assert mapped is not None
    assert mapped['published_at'] == '2023-04-07T23:20:24+02:00'
