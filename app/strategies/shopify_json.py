from __future__ import annotations
import re
import requests
from decimal import Decimal

from app.adapters.contracts import StrategyContext


class ShopifyJsonStrategy:
    name = 'shopify_json'

    def run(self, context: StrategyContext) -> list[dict]:
        cfg = context.source.source_config
        if cfg.get('use_fixture_payloads') is True:
            fixtures = cfg.get('strategy_payloads', {}).get(self.name, [])
            return fixtures if isinstance(fixtures, list) else []

        base_url = context.source.source_url.rstrip('/')
        timeout = int(cfg.get('timeouts', {}).get('product_sec', 10))
        unique: dict[int, dict] = {}
        for item in self._collect_base_pages(base_url, timeout):
            pid = item.get('id')
            if isinstance(pid, int):
                unique[pid] = item
        for item in self._collect_from_collections(base_url, timeout):
            pid = item.get('id')
            if isinstance(pid, int):
                unique[pid] = item
        return [self._map_product(item, base_url, timeout) for item in unique.values()]

    def _collect_base_pages(self, base_url: str, timeout: int) -> list[dict]:
        out: list[dict] = []
        seen_signatures: set[str] = set()
        max_pages = 12
        for page in range(1, max_pages + 1):
            response = requests.get(
                f'{base_url}/products.json',
                params={'limit': 250, 'page': page},
                timeout=timeout,
                headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/plain,*/*'},
            )
            if response.status_code != 200:
                break
            signature = response.text[:512]
            if signature in seen_signatures:
                break
            seen_signatures.add(signature)
            payload = response.json()
            items = payload.get('products', [])
            if not isinstance(items, list) or not items:
                break
            out.extend(items)
        return out

    def _collect_from_collections(self, base_url: str, timeout: int) -> list[dict]:
        out: list[dict] = []
        try:
            homepage = requests.get(base_url + '/', timeout=timeout, headers={'User-Agent': 'Mozilla/5.0'})
            if homepage.status_code != 200:
                return out
            handles = sorted(set(re.findall(r'/collections/([a-zA-Z0-9\\-_%]+)', homepage.text)))
        except Exception:
            return out

        for handle in handles[:30]:
            if not handle:
                continue
            try:
                response = requests.get(
                    f'{base_url}/collections/{handle}/products.json',
                    params={'limit': 250},
                    timeout=timeout,
                    headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/plain,*/*'},
                )
            except Exception:
                continue
            if response.status_code != 200:
                continue
            payload = response.json()
            items = payload.get('products', [])
            if isinstance(items, list) and items:
                out.extend(items)
        return out

    @staticmethod
    def _map_product(item: dict, base_url: str, timeout: int) -> dict:
        handle = str(item.get('handle') or '').strip()
        variants = item.get('variants') or []
        price = ShopifyJsonStrategy._min_variant_price(variants if isinstance(variants, list) else [])
        currency = str(item.get('currency') or '').strip().upper() or 'USD'
        if price is None and handle:
            js_price = ShopifyJsonStrategy._fallback_price_from_js(base_url, handle, currency, timeout)
            if js_price is not None:
                price = js_price
        weight = ShopifyJsonStrategy._best_variant_weight(variants if isinstance(variants, list) else [])
        images = item.get('images') if isinstance(item.get('images'), list) else []
        image_url = ''
        if images:
            first = images[0]
            if isinstance(first, dict):
                image_url = ShopifyJsonStrategy._normalize_image_url(str(first.get('src') or '').strip(), base_url)
            elif isinstance(first, str):
                image_url = ShopifyJsonStrategy._normalize_image_url(first, base_url)
        if not image_url and handle:
            js_images = ShopifyJsonStrategy._fallback_images_from_js(base_url, handle, timeout)
            if js_images:
                images = js_images
                image_url = ShopifyJsonStrategy._normalize_image_url(str(js_images[0]), base_url)
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
            response = requests.get(
                f'{base_url}/products/{handle}.js',
                timeout=timeout,
                headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/plain,*/*'},
            )
            if response.status_code != 200:
                return None
            payload = response.json()
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
            response = requests.get(
                f'{base_url}/products/{handle}.js',
                timeout=timeout,
                headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/plain,*/*'},
            )
            if response.status_code != 200:
                return []
            payload = response.json()
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
