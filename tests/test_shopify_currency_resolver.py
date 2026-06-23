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
