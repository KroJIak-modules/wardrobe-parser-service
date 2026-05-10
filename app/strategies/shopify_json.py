from __future__ import annotations
import re
from collections import Counter
from decimal import Decimal
import time

from app.adapters.contracts import StrategyContext
from app.services.run_logger import RunLogger
from app.services.shopify_http_client import ShopifyHttpClient
from app.services.shopify_policies import ShopifyJsonQualityPolicy, ShopifyPolicyFactory


class ShopifyJsonStrategy:
    name = 'shopify_json'

    def run(self, context: StrategyContext) -> list[dict]:
        cfg = context.source.source_config
        logger = RunLogger(context.run_id)

        base_url = context.source.source_url.rstrip('/')
        timeout = int(cfg.get('timeouts', {}).get('product_sec', 10))
        quality = ShopifyPolicyFactory.json_quality(cfg)
        logger.strategy_event('start', self.name, base_url=base_url)
        unique: dict[int, dict] = {}
        fail_types: Counter[str] = Counter()
        base_items = self._collect_base_pages(base_url, timeout, quality=quality, logger=logger, fail_types=fail_types)
        for item in base_items:
            pid = item.get('id')
            if isinstance(pid, int):
                unique[pid] = item
        collection_items = self._collect_from_collections(base_url, timeout, collection_limit=quality.collection_limit)
        for item in collection_items:
            pid = item.get('id')
            if isinstance(pid, int):
                unique[pid] = item
        logger.strategy_event('progress', self.name, base_items=len(base_items), collection_items=len(collection_items), dedup_items=len(unique))
        context.diagnostics.update(
            {
                'base_items': len(base_items),
                'collection_items': len(collection_items),
                'dedup_items': len(unique),
                'max_pages': quality.max_pages,
                'collection_limit': quality.collection_limit,
            }
        )
        out = [self._map_product(item, base_url, timeout, quality=quality, fail_types=fail_types) for item in unique.values()]
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
        logger: RunLogger,
        fail_types: Counter[str],
    ) -> list[dict]:
        out: list[dict] = []
        seen_signatures: set[str] = set()
        max_pages = quality.max_pages
        failed_pages: list[int] = []
        for page in range(1, max_pages + 1):
            items, state = self._fetch_products_page_with_retry(base_url, timeout, page=page, quality=quality)
            if items is None:
                fail_types[state or 'http_other'] += 1
                if state == 'antibot':
                    time.sleep(quality.antibot_pause_sec)
                failed_pages.append(page)
                continue
            if not items:
                break
            signature = f'{page}:{len(items)}:{(items[0].get("id") if items and isinstance(items[0], dict) else "")}'
            if signature in seen_signatures:
                break
            seen_signatures.add(signature)
            out.extend(items)
        if failed_pages:
            recovered = 0
            for page in failed_pages:
                items, _state = self._fetch_products_page(base_url, timeout, page=page)
                if items:
                    out.extend(items)
                    recovered += 1
                elif _state:
                    fail_types[_state] += 1
            logger.strategy_event('second_pass_done', self.name, recovered_pages=recovered, still_failed=len(failed_pages) - recovered)
        return out

    def _collect_from_collections(self, base_url: str, timeout: int, *, collection_limit: int) -> list[dict]:
        out: list[dict] = []
        if collection_limit <= 0:
            return out
        try:
            homepage = ShopifyHttpClient.get_text(base_url + '/', timeout)
            if homepage.status_code != 200:
                return out
            handles = sorted(set(re.findall(r'/collections/([a-zA-Z0-9\\-_%]+)', homepage.text)))
        except Exception:
            return out

        for handle in handles[:collection_limit]:
            if not handle:
                continue
            try:
                response = ShopifyHttpClient.get_json(
                    f'{base_url}/collections/{handle}/products.json',
                    params={'limit': 250},
                    timeout=timeout,
                )
            except Exception:
                continue
            if response.status_code != 200:
                continue
            payload = response.payload if isinstance(response.payload, dict) else {}
            items = payload.get('products', [])
            if isinstance(items, list) and items:
                out.extend(items)
        return out

    def _fetch_products_page(self, base_url: str, timeout: int, *, page: int) -> tuple[list[dict] | None, str | None]:
        try:
            response = ShopifyHttpClient.get_json(
                f'{base_url}/products.json',
                params={'limit': 250, 'page': page},
                timeout=timeout,
            )
        except Exception:
            return None, 'network'
        if response.status_code in {403, 429, 503}:
            return None, 'antibot'
        if response.status_code != 200:
            return None, 'http_other'
        if not isinstance(response.payload, dict):
            return None, 'data'
        payload = response.payload
        items = payload.get('products', [])
        if not isinstance(items, list):
            return None, 'data'
        return items, None

    def _fetch_products_page_with_retry(
        self,
        base_url: str,
        timeout: int,
        *,
        page: int,
        quality: ShopifyJsonQualityPolicy,
    ) -> tuple[list[dict] | None, str | None]:
        items, state = self._fetch_products_page(base_url, timeout, page=page)
        if items is not None:
            return items, None
        if state == 'antibot':
            time.sleep(quality.antibot_pause_sec)
            return None, state
        for wait_s in quality.retry_backoff_sec:
            time.sleep(wait_s)
            items, state = self._fetch_products_page(base_url, timeout, page=page)
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
        fail_types: Counter[str],
    ) -> dict:
        handle = str(item.get('handle') or '').strip()
        variants = item.get('variants') or []
        price = ShopifyJsonStrategy._min_variant_price(variants if isinstance(variants, list) else [])
        currency = str(item.get('currency') or '').strip().upper() or 'USD'
        if price is None and handle and 'price' in quality.enrich_from_js_fields:
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
            'price': price,
            'currency': currency,
            'weight_grams': weight,
            'variants': variants,
            'images': images,
            'image_url': image_url,
        }

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
