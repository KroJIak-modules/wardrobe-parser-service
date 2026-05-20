from __future__ import annotations

from dataclasses import dataclass


MAX_PRODUCTS_LIMIT = 50000
MAX_REQUEST_RETRIES = 5
ALLOWED_CURRENCY_CODES = {'EUR', 'USD', 'GBP', 'JPY'}
ALLOWED_CURRENCY_METHODS = {'priority_list', 'locked_param_currency', 'locked_no_currency'}


@dataclass(frozen=True)
class ShopifySitemapPolicy:
    max_products: int
    include_locale_sitemaps: bool
    request_retries: int


@dataclass(frozen=True)
class ShopifyCurrencyPolicy:
    requested_currency_priority: tuple[str, ...]
    use_storefront_currency_fallback: bool
    method: str
    locked_currency: str


@dataclass(frozen=True)
class ShopifyJsonQualityPolicy:
    antibot_pause_sec: float
    retry_backoff_sec: tuple[float, ...]
    enrich_from_js_fields: tuple[str, ...]


@dataclass(frozen=True)
class ShopifyJsQualityPolicy:
    progress_every: int
    wait_log_sec: float
    pause_poll_sec: float
    antibot_pause_sec: float
    retry_backoff_sec: tuple[float, ...]

@dataclass(frozen=True)
class ShopifyBrowserExtensionQualityPolicy:
    progress_every: int
    retry_backoff_sec: tuple[float, ...]


class ShopifyPolicyFactory:
    @staticmethod
    def currency(config: dict) -> ShopifyCurrencyPolicy:
        raw = config.get('shopify_currency') if isinstance(config.get('shopify_currency'), dict) else {}
        normalized_priority = tuple(
            code
            for code in (
                'GBP' if str(x).strip().upper() == 'GBR' else str(x).strip().upper()
                for x in (raw.get('requested_currency_priority') or [])
                if str(x).strip()
            )
            if code in ALLOWED_CURRENCY_CODES
        )
        raw_method = str(raw.get('method') or '').strip().lower()
        method = raw_method if raw_method in ALLOWED_CURRENCY_METHODS else 'priority_list'
        locked_currency = ''
        if method in {'locked_param_currency', 'locked_no_currency'}:
            candidate = str(raw.get('locked_currency') or '').strip().upper()
            if candidate == 'GBR':
                candidate = 'GBP'
            if candidate in ALLOWED_CURRENCY_CODES:
                locked_currency = candidate
            elif normalized_priority:
                locked_currency = normalized_priority[0]
        return ShopifyCurrencyPolicy(
            requested_currency_priority=normalized_priority,
            use_storefront_currency_fallback=bool(raw.get('use_storefront_currency_fallback')),
            method=method,
            locked_currency=locked_currency,
        )

    @staticmethod
    def sitemap(config: dict) -> ShopifySitemapPolicy:
        raw = config.get('shopify_sitemap') if isinstance(config.get('shopify_sitemap'), dict) else {}
        return ShopifySitemapPolicy(
            max_products=int(raw.get('max_products')),
            include_locale_sitemaps=bool(raw.get('include_locale_sitemaps')),
            request_retries=int(raw.get('request_retries')),
        )

    @staticmethod
    def json_quality(config: dict) -> ShopifyJsonQualityPolicy:
        raw = config.get('shopify_json_quality') if isinstance(config.get('shopify_json_quality'), dict) else {}
        return ShopifyJsonQualityPolicy(
            antibot_pause_sec=float(raw.get('antibot_pause_sec')),
            retry_backoff_sec=tuple(float(x) for x in (raw.get('retry_backoff_sec') or [])),
            enrich_from_js_fields=tuple(str(x).strip() for x in (raw.get('enrich_from_js_fields') or []) if str(x).strip()),
        )

    @staticmethod
    def js_quality(config: dict) -> ShopifyJsQualityPolicy:
        raw = config.get('shopify_js_quality') if isinstance(config.get('shopify_js_quality'), dict) else {}
        return ShopifyJsQualityPolicy(
            progress_every=int(raw.get('progress_every')),
            wait_log_sec=float(raw.get('wait_log_sec')),
            pause_poll_sec=float(raw.get('pause_poll_sec')),
            antibot_pause_sec=float(raw.get('antibot_pause_sec')),
            retry_backoff_sec=tuple(float(x) for x in (raw.get('retry_backoff_sec') or [])),
        )

    @staticmethod
    def browser_extension_quality(config: dict) -> ShopifyBrowserExtensionQualityPolicy:
        raw = (
            config.get('shopify_browser_extension_quality')
            if isinstance(config.get('shopify_browser_extension_quality'), dict)
            else {}
        )
        return ShopifyBrowserExtensionQualityPolicy(
            progress_every=int(raw.get('progress_every')),
            retry_backoff_sec=tuple(float(x) for x in (raw.get('retry_backoff_sec') or [])),
        )
