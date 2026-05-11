from __future__ import annotations

from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import Counter
import threading
from urllib.parse import urlparse
import time

from app.adapters.contracts import StrategyContext
from app.services.shopify_currency_resolver import ShopifyCurrencyResolver
from app.services.run_logger import RunLogger
from app.services.shopify_http_client import ShopifyHttpClient
from app.services.shopify_policies import ShopifyJsQualityPolicy, ShopifyPolicyFactory, ShopifySitemapPolicy
from app.services.shopify_sitemap_discovery import ShopifySitemapDiscovery


class ShopifyJsStrategy:
    name = 'shopify_js'

    def run(self, context: StrategyContext) -> list[dict]:
        cfg = context.source.source_config
        logger = RunLogger(context.run_id)

        base_url = context.source.source_url.rstrip('/')
        timeout = int(cfg.get('timeouts', {}).get('product_sec', 10))
        sitemap_policy = ShopifyPolicyFactory.sitemap(cfg)
        currency_policy = ShopifyPolicyFactory.currency(cfg)
        storefront_currency = ''
        storefront_currency_source = 'disabled'
        if currency_policy.requested_currency:
            storefront_currency = currency_policy.requested_currency
            storefront_currency_source = 'shopify_currency_requested'
        elif currency_policy.use_storefront_currency_fallback:
            storefront_currency, storefront_currency_source = ShopifyCurrencyResolver.resolve_storefront_currency(
                base_url,
                timeout,
                currency_policy.allowed_currencies,
            )
        quality = ShopifyPolicyFactory.js_quality(cfg)
        workers = max(1, int(cfg['shopify_js_workers']))
        product_urls = self._get_product_urls(base_url, timeout, policy=sitemap_policy)
        total = len(product_urls)
        logger.strategy_event('start', self.name, base_url=base_url, total=total, workers=workers)

        out: list[dict] = []
        failed_urls: list[str] = []
        fail_types: Counter[str] = Counter()
        processed = 0
        pause_until_ts = 0.0
        pause_lock = threading.Lock()

        def wait_if_paused() -> None:
            nonlocal pause_until_ts
            while True:
                with pause_lock:
                    now = time.time()
                    if now >= pause_until_ts:
                        return
                    sleep_for = pause_until_ts - now
                time.sleep(min(quality.pause_poll_sec, max(0.01, sleep_for)))

        def activate_pause(sec: float) -> None:
            nonlocal pause_until_ts
            with pause_lock:
                until = time.time() + sec
                if until > pause_until_ts:
                    pause_until_ts = until

        def worker(url: str) -> tuple[str, dict | None, str | None]:
            wait_if_paused()
            item, fail_type = self._parse_product_js_with_retry(
                base_url,
                url,
                timeout,
                activate_pause=activate_pause,
                quality=quality,
                allowed_currencies=currency_policy.allowed_currencies,
                storefront_currency=storefront_currency,
            )
            return url, item, fail_type

        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(worker, u): u for u in product_urls}
            while pending:
                done, not_done = wait(pending.keys(), timeout=quality.wait_log_sec, return_when=FIRST_COMPLETED)
                if not done:
                    pct = (processed / total) * 100 if total else 100
                    logger.strategy_event(
                        'progress',
                        self.name,
                        processed=f'{processed}/{total}',
                        pct=f'{pct:.2f}%',
                        ok=len(out),
                        fail=len(failed_urls),
                        antibot=fail_types.get('antibot', 0),
                        network=fail_types.get('network', 0),
                        data=fail_types.get('data', 0),
                        http_other=fail_types.get('http_other', 0),
                    )
                    continue
                for fut in done:
                    pending.pop(fut, None)
                    url, item, fail_type = fut.result()
                    processed += 1
                    if item is not None:
                        out.append(item)
                    else:
                        failed_urls.append(url)
                    if fail_type:
                        fail_types[fail_type] += 1
                    if total > 0 and (processed % quality.progress_every == 0 or processed == total):
                        pct = (processed / total) * 100
                        logger.strategy_event(
                            'progress',
                            self.name,
                            processed=f'{processed}/{total}',
                            pct=f'{pct:.2f}%',
                            ok=len(out),
                            fail=len(failed_urls),
                            antibot=fail_types.get('antibot', 0),
                            network=fail_types.get('network', 0),
                            data=fail_types.get('data', 0),
                            http_other=fail_types.get('http_other', 0),
                        )

        if failed_urls:
            recovered = 0
            for url in failed_urls:
                item = self._parse_product_js(
                    base_url,
                    url,
                    timeout,
                    allowed_currencies=currency_policy.allowed_currencies,
                    storefront_currency=storefront_currency,
                )
                if item is not None:
                    out.append(item)
                    recovered += 1
            logger.strategy_event('second_pass_done', self.name, recovered=recovered, still_failed=len(failed_urls) - recovered)
            context.diagnostics.update({
                'discovered_urls': total,
                'processed_urls': processed,
                'parsed_products': len(out),
                'first_pass_failed_urls': len(failed_urls),
                'second_pass_recovered': recovered,
                'second_pass_failed': len(failed_urls) - recovered,
                'fail_antibot': int(fail_types.get('antibot', 0)),
                'fail_network': int(fail_types.get('network', 0)),
                'fail_data': int(fail_types.get('data', 0)),
                'fail_http_other': int(fail_types.get('http_other', 0)),
                'workers': workers,
                'max_products': sitemap_policy.max_products,
                'storefront_currency': storefront_currency,
                'storefront_currency_source': storefront_currency_source,
            })
        else:
            context.diagnostics.update({
                'discovered_urls': total,
                'processed_urls': processed,
                'parsed_products': len(out),
                'first_pass_failed_urls': 0,
                'second_pass_recovered': 0,
                'second_pass_failed': 0,
                'fail_antibot': int(fail_types.get('antibot', 0)),
                'fail_network': int(fail_types.get('network', 0)),
                'fail_data': int(fail_types.get('data', 0)),
                'fail_http_other': int(fail_types.get('http_other', 0)),
                'workers': workers,
                'max_products': sitemap_policy.max_products,
                'storefront_currency': storefront_currency,
                'storefront_currency_source': storefront_currency_source,
            })
        logger.strategy_event('done', self.name, parsed=len(out), total=total)
        return out

    @staticmethod
    def _get_product_urls(base_url: str, timeout: int, *, policy: ShopifySitemapPolicy) -> list[str]:
        return ShopifySitemapDiscovery.discover_product_urls(base_url, timeout, policy)

    @staticmethod
    def _build_js_urls(base_url: str, product_url: str, handle: str) -> list[str]:
        parsed = urlparse(product_url)
        direct_path = (parsed.path or '').strip('/')
        urls: list[str] = []
        if direct_path:
            urls.append(f'{base_url}/{direct_path}.js')
        urls.append(f'{base_url}/products/{handle}.js')
        dedup: list[str] = []
        seen: set[str] = set()
        for value in urls:
            if value in seen:
                continue
            seen.add(value)
            dedup.append(value)
        return dedup

    @staticmethod
    def _parse_product_js(
        base_url: str,
        product_url: str,
        timeout: int,
        *,
        allowed_currencies: tuple[str, ...],
        storefront_currency: str,
    ) -> dict | None:
        handle = ShopifyJsStrategy._extract_handle(product_url)
        if not handle:
            return None

        payload: dict | None = None
        for js_url in ShopifyJsStrategy._build_js_urls(base_url, product_url, handle):
            params = {'currency': storefront_currency} if storefront_currency else None
            response = ShopifyHttpClient.get_json(js_url, timeout, params=params)
            if response.status_code != 200:
                continue
            payload = response.payload
            break
        if not isinstance(payload, dict):
            return None

        variants = payload.get('variants') if isinstance(payload.get('variants'), list) else []
        currency = ShopifyJsStrategy._resolve_currency(payload.get('currency'), storefront_currency, allowed_currencies)
        price = ShopifyJsStrategy._min_variant_price(variants, currency)
        weight_grams = ShopifyJsStrategy._best_variant_weight(variants)
        images = payload.get('images') if isinstance(payload.get('images'), list) else []
        normalized_images = [ShopifyJsStrategy._normalize_image_url(str(x), base_url) for x in images if str(x).strip()]
        normalized_images = [x for x in normalized_images if x]
        image_url = normalized_images[0] if normalized_images else ''

        return {
            'url': f'{base_url}/products/{handle}',
            'handle': handle,
            'title': str(payload.get('title') or '').strip(),
            'product_type': str(payload.get('type') or '').strip(),
            'tags': payload.get('tags') if isinstance(payload.get('tags'), list) else [],
            'price': price,
            'currency': currency,
            'weight_grams': weight_grams,
            'variants': variants,
            'images': normalized_images,
            'image_url': image_url,
        }

    @staticmethod
    def _parse_product_js_with_retry(
        base_url: str,
        product_url: str,
        timeout: int,
        *,
        activate_pause,
        quality: ShopifyJsQualityPolicy,
        allowed_currencies: tuple[str, ...],
        storefront_currency: str,
    ) -> tuple[dict | None, str | None]:
        backoffs = quality.retry_backoff_sec
        result, fail_type = ShopifyJsStrategy._parse_with_classification(
            base_url,
            product_url,
            timeout,
            allowed_currencies=allowed_currencies,
            storefront_currency=storefront_currency,
        )
        if result is not None:
            return result, None
        if fail_type == 'antibot':
            activate_pause(quality.antibot_pause_sec)
            return None, fail_type
        for wait_s in backoffs:
            time.sleep(wait_s)
            result, fail_type = ShopifyJsStrategy._parse_with_classification(
                base_url,
                product_url,
                timeout,
                allowed_currencies=allowed_currencies,
                storefront_currency=storefront_currency,
            )
            if result is not None:
                return result, None
            if fail_type == 'antibot':
                activate_pause(quality.antibot_pause_sec)
                return None, fail_type
        return None, fail_type

    @staticmethod
    def _parse_with_classification(
        base_url: str,
        product_url: str,
        timeout: int,
        *,
        allowed_currencies: tuple[str, ...],
        storefront_currency: str,
    ) -> tuple[dict | None, str | None]:
        handle = ShopifyJsStrategy._extract_handle(product_url)
        if not handle:
            return None, 'data'
        payload: dict | None = None
        last_fail: str | None = None
        for js_url in ShopifyJsStrategy._build_js_urls(base_url, product_url, handle):
            try:
                params = {'currency': storefront_currency} if storefront_currency else None
                response = ShopifyHttpClient.get_json(js_url, timeout, params=params)
            except Exception:
                last_fail = 'network'
                continue
            if response.status_code in {403, 429, 503}:
                return None, 'antibot'
            if response.status_code != 200:
                last_fail = 'http_other'
                continue
            candidate = response.payload
            if candidate is None:
                last_fail = 'data'
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break
            last_fail = 'data'
        if payload is None:
            return None, last_fail or 'http_other'
        if not isinstance(payload, dict):
            return None, 'data'
        variants = payload.get('variants') if isinstance(payload.get('variants'), list) else []
        currency = ShopifyJsStrategy._resolve_currency(payload.get('currency'), storefront_currency, allowed_currencies)
        price = ShopifyJsStrategy._min_variant_price(variants, currency)
        weight_grams = ShopifyJsStrategy._best_variant_weight(variants)
        images = payload.get('images') if isinstance(payload.get('images'), list) else []
        normalized_images = [ShopifyJsStrategy._normalize_image_url(str(x), base_url) for x in images if str(x).strip()]
        normalized_images = [x for x in normalized_images if x]
        image_url = normalized_images[0] if normalized_images else ''
        return {
            'url': f'{base_url}/products/{handle}',
            'handle': handle,
            'title': str(payload.get('title') or '').strip(),
            'product_type': str(payload.get('type') or '').strip(),
            'tags': payload.get('tags') if isinstance(payload.get('tags'), list) else [],
            'price': price,
            'currency': currency,
            'weight_grams': weight_grams,
            'variants': variants,
            'images': normalized_images,
            'image_url': image_url,
        }, None

    @staticmethod
    def _resolve_currency(raw_currency: object, storefront_currency: str, allowed_currencies: tuple[str, ...]) -> str:
        allowed = {ShopifyCurrencyResolver.normalize(x) for x in allowed_currencies}
        raw = ShopifyCurrencyResolver.normalize(raw_currency)
        if raw and raw in allowed:
            return raw
        storefront = ShopifyCurrencyResolver.normalize(storefront_currency)
        if storefront and storefront in allowed:
            return storefront
        return ''

    @staticmethod
    def _extract_handle(product_url: str) -> str:
        return ShopifySitemapDiscovery.extract_handle(product_url)

    @staticmethod
    def _min_variant_price(variants: list[dict], currency: str) -> float | None:
        minor_values: list[int] = []
        decimal_values: list[float] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            raw = variant.get('price')
            if isinstance(raw, int):
                if raw > 0:
                    minor_values.append(raw)
                continue
            try:
                val = float(raw)
            except Exception:
                continue
            if val > 0:
                decimal_values.append(val)
        if minor_values:
            scale = ShopifyJsStrategy._currency_scale(currency)
            return float(Decimal(min(minor_values)) / (Decimal(10) ** scale))
        return min(decimal_values) if decimal_values else None

    @staticmethod
    def _best_variant_weight(variants: list[dict]) -> int | None:
        values: list[int] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            raw = variant.get('grams')
            if raw is None:
                raw = variant.get('weight')
            try:
                grams = int(raw)
            except Exception:
                continue
            if grams > 0:
                values.append(grams)
        return min(values) if values else None

    @staticmethod
    def _normalize_image_url(value: str, base_url: str) -> str:
        raw = (value or '').strip()
        if not raw:
            return ''
        if raw.startswith('//'):
            return 'https:' + raw
        if raw.startswith('/'):
            return base_url.rstrip('/') + raw
        return raw

    @staticmethod
    def _currency_scale(currency: str) -> int:
        c = (currency or '').upper()
        if c in {'JPY', 'KRW', 'VND'}:
            return 0
        if c in {'BHD', 'IQD', 'JOD', 'KWD', 'LYD', 'OMR', 'TND'}:
            return 3
        return 2
