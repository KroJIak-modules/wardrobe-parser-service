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


def test_currency_policy_flag_is_site_configured() -> None:
    from app.services.shopify_policies import ShopifyPolicyFactory

    disabled = ShopifyPolicyFactory.currency({
        'shopify_currency': {
            'allowed_currencies': ['EUR', 'USD', 'GBP'],
            'use_storefront_currency_fallback': False,
        }
    })
    enabled = ShopifyPolicyFactory.currency({
        'shopify_currency': {
            'allowed_currencies': ['EUR', 'USD', 'GBP'],
            'use_storefront_currency_fallback': True,
        }
    })
    assert disabled.use_storefront_currency_fallback is False
    assert enabled.use_storefront_currency_fallback is True


def test_currency_policy_requested_currency_is_normalized() -> None:
    from app.services.shopify_policies import ShopifyPolicyFactory

    policy = ShopifyPolicyFactory.currency({
        'shopify_currency': {
            'allowed_currencies': ['EUR', 'USD', 'GBR'],
            'use_storefront_currency_fallback': True,
            'requested_currency': 'gbr',
        }
    })
    assert policy.requested_currency == 'GBP'


def test_shopify_js_weight_accepts_weight_field() -> None:
    from app.strategies.shopify_js import ShopifyJsStrategy

    assert ShopifyJsStrategy._best_variant_weight([
        {'title': 'S', 'weight': 310},
        {'title': 'M', 'weight': 315},
    ]) == 310
