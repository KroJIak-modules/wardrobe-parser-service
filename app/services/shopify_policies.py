from __future__ import annotations

from dataclasses import dataclass


MAX_PRODUCTS_LIMIT = 50000
MAX_REQUEST_RETRIES = 5
ALLOWED_CURRENCY_CODES = {'EUR', 'USD', 'GBP', 'JPY'}
ALLOWED_REQUEST_MODES = {'prefer_list', 'fixed_param', 'fixed_ambient'}


@dataclass(frozen=True)
class ShopifySitemapPolicy:
    max_products: int
    include_locale_sitemaps: bool
    request_retries: int


@dataclass(frozen=True)
class ShopifyCurrencyPolicy:
    preferred_currencies: tuple[str, ...]
    request_mode: str
    fixed_currency: str
    fixed_country: str


@dataclass(frozen=True)
class ShopifyJsonQualityPolicy:
    antibot_pause_sec: float
    retry_backoff_sec: tuple[float, ...]
    enrich_from_js_fields: tuple[str, ...]
    page_interval_sec: float


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
        raw = config.get('shopify_market') if isinstance(config.get('shopify_market'), dict) else {}
        preferred_currencies = tuple(
            code
            for code in (
                'GBP' if str(x).strip().upper() == 'GBR' else str(x).strip().upper()
                for x in (raw.get('preferred_currencies') or [])
                if str(x).strip()
            )
            if code in ALLOWED_CURRENCY_CODES
        )
        raw_request_mode = str(raw.get('request_mode') or '').strip().lower()
        request_mode = raw_request_mode if raw_request_mode in ALLOWED_REQUEST_MODES else 'prefer_list'
        fixed_currency = ''
        if request_mode in {'fixed_param', 'fixed_ambient'}:
            candidate = str(raw.get('fixed_currency') or '').strip().upper()
            if candidate == 'GBR':
                candidate = 'GBP'
            if candidate in ALLOWED_CURRENCY_CODES:
                fixed_currency = candidate
            elif preferred_currencies:
                fixed_currency = preferred_currencies[0]
        raw_country = str(raw.get('fixed_country') or '').strip().upper()
        fixed_country = raw_country if len(raw_country) == 2 and raw_country.isalpha() else ''
        return ShopifyCurrencyPolicy(
            preferred_currencies=preferred_currencies,
            request_mode=request_mode,
            fixed_currency=fixed_currency,
            fixed_country=fixed_country,
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
            # Shopify catalogue endpoints tolerate steady, sequential polling far
            # better than short request bursts. Sources may override this value.
            page_interval_sec=float(raw.get('page_interval_sec', 0.15)),
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
