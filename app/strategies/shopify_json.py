from __future__ import annotations
from collections import Counter
from decimal import Decimal
import time

from app.adapters.contracts import StrategyContext
from app.services.shopify_currency_resolver import ShopifyCurrencyResolver
from app.services.run_logger import RunLogger
from app.services.shopify_http_client import ShopifyHttpClient
from app.services.shopify_policies import ShopifyJsonQualityPolicy, ShopifyPolicyFactory


class ShopifyJsonStrategy:
    name = 'shopify_json'
    PAGE_LIMIT = 250

    def run(self, context: StrategyContext) -> list[dict]:
        cfg = context.source.source_config
        logger = RunLogger(context.run_id)

        base_url = context.source.source_url.rstrip('/')
        timeout = int(cfg.get('timeouts', {}).get('product_sec', 10))
        quality = ShopifyPolicyFactory.json_quality(cfg)
        sitemap_policy = ShopifyPolicyFactory.sitemap(cfg)
        currency_policy = ShopifyPolicyFactory.currency(cfg)
        storefront_currency = ''
        storefront_currency_source = 'disabled'
        requested_priority = list(currency_policy.requested_currency_priority)
        if requested_priority:
            storefront_currency = requested_priority[0]
            storefront_currency_source = 'shopify_currency_requested_priority'
        elif currency_policy.use_storefront_currency_fallback:
            storefront_currency, storefront_currency_source = ShopifyCurrencyResolver.resolve_storefront_currency(
                base_url,
                timeout,
                ('EUR', 'USD', 'GBP'),
            )
        logger.strategy_event('start', self.name, base_url=base_url, max_products=sitemap_policy.max_products)
        unique: dict[int, dict] = {}
        fail_types: Counter[str] = Counter()
        base_items, pages_fetched = self._collect_base_pages(
            base_url,
            timeout,
            quality=quality,
            max_products=sitemap_policy.max_products,
            storefront_currency=storefront_currency,
            currency_priority=tuple(requested_priority),
            logger=logger,
            fail_types=fail_types,
        )
        for item in base_items:
            pid = item.get('id')
            if isinstance(pid, int):
                unique[pid] = item
        logger.strategy_event('progress', self.name, pages_fetched=pages_fetched, base_items=len(base_items), dedup_items=len(unique))
        context.diagnostics.update(
            {
                'pages_fetched': pages_fetched,
                'page_limit': self.PAGE_LIMIT,
                'max_products': sitemap_policy.max_products,
                'storefront_currency': storefront_currency,
                'storefront_currency_source': storefront_currency_source,
                'base_items': len(base_items),
                'dedup_items': len(unique),
            }
        )
        out = [
            self._map_product(
                item,
                base_url,
                timeout,
                quality=quality,
                allowed_currencies=('EUR', 'USD', 'GBP'),
                storefront_currency=storefront_currency,
                fail_types=fail_types,
            )
            for item in unique.values()
        ]
        context.diagnostics.update(
            {
                'fail_antibot': int(fail_types.get('antibot', 0)),
                'fail_network': int(fail_types.get('network', 0)),
                'fail_data': int(fail_types.get('data', 0)),
                'fail_http_other': int(fail_types.get('http_other', 0)),
                'js_enrich_price': int(fail_types.get('js_enrich_price', 0)),
                'js_enrich_images': int(fail_types.get('js_enrich_images', 0)),
            }
        )
        logger.strategy_event('done', self.name, parsed=len(out))
        return out

    def _collect_base_pages(
        self,
        base_url: str,
        timeout: int,
        *,
        quality: ShopifyJsonQualityPolicy,
        max_products: int,
        storefront_currency: str,
        currency_priority: tuple[str, ...],
        logger: RunLogger,
        fail_types: Counter[str],
    ) -> tuple[list[dict], int]:
        out: list[dict] = []
        seen_signatures: set[str] = set()
        failed_pages: list[int] = []
        pages_fetched = 0
        page = 1
        while len(out) < max_products:
            items, state = self._fetch_products_page_with_retry(
                base_url,
                timeout,
                page=page,
                storefront_currency=storefront_currency,
                currency_priority=currency_priority,
                quality=quality,
            )
            if items is None:
                fail_types[state or 'http_other'] += 1
                if state == 'antibot':
                    time.sleep(quality.antibot_pause_sec)
                failed_pages.append(page)
                page += 1
                continue
            pages_fetched += 1
            if not items:
                break
            signature = self._page_signature(items)
            if signature in seen_signatures:
                logger.strategy_event('page_loop_detected', self.name, page=page, pages_fetched=pages_fetched)
                break
            seen_signatures.add(signature)
            remaining = max_products - len(out)
            out.extend(items[:remaining])
            if len(items) < self.PAGE_LIMIT:
                break
            page += 1
        if failed_pages and len(out) < max_products:
            recovered = 0
            for page in failed_pages:
                if len(out) >= max_products:
                    break
                items, _state = self._fetch_products_page(
                    base_url, timeout, page=page, storefront_currency=storefront_currency, currency_priority=currency_priority
                )
                if items:
                    remaining = max_products - len(out)
                    out.extend(items[:remaining])
                    recovered += 1
                elif _state:
                    fail_types[_state] += 1
            logger.strategy_event('second_pass_done', self.name, recovered_pages=recovered, still_failed=len(failed_pages) - recovered)
        return out, pages_fetched

    @staticmethod
    def _page_signature(items: list[dict]) -> str:
        first_id = items[0].get('id') if items and isinstance(items[0], dict) else ''
        last_id = items[-1].get('id') if items and isinstance(items[-1], dict) else ''
        return f'{len(items)}:{first_id}:{last_id}'

    def _fetch_products_page(
        self, base_url: str, timeout: int, *, page: int, storefront_currency: str, currency_priority: tuple[str, ...]
    ) -> tuple[list[dict] | None, str | None]:
        currencies = [x for x in currency_priority if x] or ([storefront_currency] if storefront_currency else [''])
        last_state: str | None = None
        for cur in currencies:
            try:
                params = {'limit': self.PAGE_LIMIT, 'page': page}
                if cur:
                    params['currency'] = cur
                response = ShopifyHttpClient.get_json(f'{base_url}/products.json', params=params, timeout=timeout)
            except Exception:
                last_state = 'network'
                continue
            if response.status_code in {403, 429, 503}:
                return None, 'antibot'
            if response.status_code != 200:
                last_state = 'http_other'
                continue
            if not isinstance(response.payload, dict):
                last_state = 'data'
                continue
            items = response.payload.get('products', [])
            if not isinstance(items, list):
                last_state = 'data'
                continue
            return items, None
        return None, last_state or 'http_other'

    def _fetch_products_page_with_retry(
        self,
        base_url: str,
        timeout: int,
        *,
        page: int,
        storefront_currency: str,
        currency_priority: tuple[str, ...],
        quality: ShopifyJsonQualityPolicy,
    ) -> tuple[list[dict] | None, str | None]:
        items, state = self._fetch_products_page(
            base_url, timeout, page=page, storefront_currency=storefront_currency, currency_priority=currency_priority
        )
        if items is not None:
            return items, None
        if state == 'antibot':
            time.sleep(quality.antibot_pause_sec)
            return None, state
        for wait_s in quality.retry_backoff_sec:
            time.sleep(wait_s)
            items, state = self._fetch_products_page(
                base_url, timeout, page=page, storefront_currency=storefront_currency, currency_priority=currency_priority
            )
            if items is not None:
                return items, None
            if state == 'antibot':
                time.sleep(quality.antibot_pause_sec)
                return None, state
        return None, state

    @staticmethod
    def _map_product(
        item: dict,
        base_url: str,
        timeout: int,
        *,
        quality: ShopifyJsonQualityPolicy,
        allowed_currencies: tuple[str, ...],
        storefront_currency: str,
        fail_types: Counter[str],
    ) -> dict:
        handle = str(item.get('handle') or '').strip()
        variants = item.get('variants') or []
        price = ShopifyJsonStrategy._min_variant_price(variants if isinstance(variants, list) else [])
        currency = ShopifyJsonStrategy._resolve_currency(item.get('currency'), storefront_currency, allowed_currencies)
        if price is None and currency and handle and 'price' in quality.enrich_from_js_fields:
            js_price = ShopifyJsonStrategy._fallback_price_from_js(base_url, handle, currency, timeout)
            if js_price is not None:
                price = js_price
                fail_types['js_enrich_price'] += 1
        weight = ShopifyJsonStrategy._best_variant_weight(variants if isinstance(variants, list) else [])
        images = item.get('images') if isinstance(item.get('images'), list) else []
        image_url = ''
        if images:
            first = images[0]
            if isinstance(first, dict):
                image_url = ShopifyJsonStrategy._normalize_image_url(str(first.get('src') or '').strip(), base_url)
            elif isinstance(first, str):
                image_url = ShopifyJsonStrategy._normalize_image_url(first, base_url)
        if not image_url and handle and 'images' in quality.enrich_from_js_fields:
            js_images = ShopifyJsonStrategy._fallback_images_from_js(base_url, handle, timeout)
            if js_images:
                images = js_images
                image_url = ShopifyJsonStrategy._normalize_image_url(str(js_images[0]), base_url)
                fail_types['js_enrich_images'] += 1
        return {
            'url': f'{base_url}/products/{handle}' if handle else '',
            'handle': handle,
            'title': str(item.get('title') or '').strip(),
            'vendor': str(item.get('vendor') or '').strip(),
            'product_type': str(item.get('product_type') or '').strip(),
            'tags': item.get('tags') if isinstance(item.get('tags'), list) else [],
            'price': price,
            'currency': currency,
            'weight_grams': weight,
            'variants': variants,
            'images': images,
            'image_url': image_url,
        }

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
    def _min_variant_price(variants: list[dict]) -> float | None:
        values: list[float] = []
        for v in variants:
            if not isinstance(v, dict):
                continue
            raw = v.get('price')
            try:
                val = float(raw)
            except Exception:
                continue
            if val > 0:
                values.append(val)
        return min(values) if values else None

    @staticmethod
    def _best_variant_weight(variants: list[dict]) -> int | None:
        values: list[int] = []
        for v in variants:
            if not isinstance(v, dict):
                continue
            raw = v.get('grams')
            try:
                val = int(raw)
            except Exception:
                continue
            if val > 0:
                values.append(val)
        return min(values) if values else None

    @staticmethod
    def _fallback_price_from_js(base_url: str, handle: str, currency: str, timeout: int) -> float | None:
        try:
            response = ShopifyHttpClient.get_json(f'{base_url}/products/{handle}.js', timeout)
            if response.status_code != 200:
                return None
            payload = response.payload if isinstance(response.payload, dict) else {}
            variants = payload.get('variants') or []
            minor_values: list[int] = []
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                raw = variant.get('price')
                try:
                    val = int(raw)
                except Exception:
                    continue
                if val > 0:
                    minor_values.append(val)
            if not minor_values:
                return None
            scale = ShopifyJsonStrategy._currency_scale(currency)
            return float(Decimal(min(minor_values)) / (Decimal(10) ** scale))
        except Exception:
            return None

    @staticmethod
    def _fallback_images_from_js(base_url: str, handle: str, timeout: int) -> list[str]:
        try:
            response = ShopifyHttpClient.get_json(f'{base_url}/products/{handle}.js', timeout)
            if response.status_code != 200:
                return []
            payload = response.payload if isinstance(response.payload, dict) else {}
            raw_images = payload.get('images') or []
            out: list[str] = []
            for raw in raw_images:
                if not isinstance(raw, str):
                    continue
                normalized = ShopifyJsonStrategy._normalize_image_url(raw, base_url)
                if normalized:
                    out.append(normalized)
            return out
        except Exception:
            return []

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
