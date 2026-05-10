from __future__ import annotations

from dataclasses import dataclass


MAX_PRODUCTS_LIMIT = 50000
MAX_REQUEST_RETRIES = 5
MAX_JSON_PAGES = 200
MAX_COLLECTION_LIMIT = 200


@dataclass(frozen=True)
class ShopifySitemapPolicy:
    max_products: int
    include_locale_sitemaps: bool
    request_retries: int


@dataclass(frozen=True)
class ShopifyJsonQualityPolicy:
    max_pages: int
    collection_limit: int
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


class ShopifyPolicyFactory:
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
            max_pages=int(raw.get('max_pages')),
            collection_limit=int(raw.get('collection_limit')),
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
