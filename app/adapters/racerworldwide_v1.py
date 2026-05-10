from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlparse
import requests

from app.adapters.contracts import SiteAdapter, SourceContext


class RacerworldwideV1Adapter:
    adapter_key = 'racerworldwide__v1'
    allowed_strategies = ('shopify_json', 'shopify_js', 'browser_export')

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        base_url = context.source_url.rstrip('/')
        timeout = int((context.source_config.get('timeouts') or {}).get('product_sec', 10))
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/plain,*/*'}
        unique_urls: set[str] = set()

        for page in range(1, 13):
            try:
                response = requests.get(
                    f'{base_url}/products.json',
                    params={'limit': 250, 'page': page},
                    headers=headers,
                    timeout=timeout,
                )
            except Exception:
                continue
            if response.status_code != 200:
                continue
            items = response.json().get('products', [])
            if not isinstance(items, list):
                continue
            for item in items:
                handle = str((item or {}).get('handle') or '').strip()
                if handle:
                    unique_urls.add(f'{base_url}/products/{handle}')

        try:
            home = requests.get(base_url + '/', headers={'User-Agent': 'Mozilla/5.0'}, timeout=timeout)
            handles = sorted(set(re.findall(r'/collections/([a-zA-Z0-9\\-_%]+)', home.text)))
        except Exception:
            handles = []
        for handle in handles[:30]:
            if not handle:
                continue
            try:
                response = requests.get(
                    f'{base_url}/collections/{handle}/products.json',
                    params={'limit': 250},
                    headers=headers,
                    timeout=timeout,
                )
            except Exception:
                continue
            if response.status_code != 200:
                continue
            items = response.json().get('products', [])
            if not isinstance(items, list):
                continue
            for item in items:
                product_handle = str((item or {}).get('handle') or '').strip()
                if product_handle:
                    unique_urls.add(f'{base_url}/products/{product_handle}')

        return sorted(unique_urls)

    def normalize_product(self, raw_product: dict) -> dict:
        url = str(raw_product.get('url') or '').strip()
        handle = self._extract_handle(url)
        title = str(raw_product.get('title') or '').strip()

        price = self._to_decimal(raw_product.get('price'))
        currency = str(raw_product.get('currency') or '').strip().upper()
        weight_grams = self._to_decimal(raw_product.get('weight_grams'))

        variants = raw_product.get('variants')
        if not isinstance(variants, list) or not variants:
            variants = [{'title': 'default', 'available': True}]

        return {
            'url': url,
            'handle': handle,
            'title': title,
            'price': price,
            'currency': currency,
            'weight_grams': weight_grams,
            'image_url': self._first_image(raw_product),
            'variants': variants,
        }

    def validate_product(self, normalized_product: dict) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        if not normalized_product.get('url'):
            reasons.append('missing_url')
        if not normalized_product.get('handle'):
            reasons.append('missing_handle')
        if not normalized_product.get('title'):
            reasons.append('missing_title')

        price = normalized_product.get('price')
        if price is None or price <= Decimal('0'):
            reasons.append('missing_price')

        currency = normalized_product.get('currency')
        if not currency or len(str(currency)) != 3:
            reasons.append('missing_currency')

        weight_grams = normalized_product.get('weight_grams')
        weight_source = str(normalized_product.get('weight_source') or '').strip().lower()
        if weight_source == 'missing' or weight_grams is None or weight_grams <= Decimal('0'):
            reasons.append('missing_weight')

        variants = normalized_product.get('variants')
        if not isinstance(variants, list) or not variants:
            reasons.append('missing_variants')

        return (len(reasons) == 0, reasons)

    @staticmethod
    def _extract_handle(url: str) -> str:
        if not url:
            return ''
        parsed = urlparse(url)
        path = (parsed.path or '').strip('/')
        if '/products/' in f'/{path}/':
            return path.split('/products/')[-1].strip('/')
        chunks = [chunk for chunk in path.split('/') if chunk]
        return chunks[-1] if chunks else ''

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _first_image(raw_product: dict) -> str:
        base_url = str(raw_product.get('url') or '').strip()
        image_url = RacerworldwideV1Adapter._normalize_image_url(str(raw_product.get('image_url') or '').strip(), base_url)
        if image_url:
            return image_url
        images = raw_product.get('images')
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                return RacerworldwideV1Adapter._normalize_image_url(str(first.get('src') or '').strip(), base_url)
            return RacerworldwideV1Adapter._normalize_image_url(str(first).strip(), base_url)
        return ''

    @staticmethod
    def _normalize_image_url(value: str, product_url: str) -> str:
        raw = (value or '').strip()
        if not raw:
            return ''
        if raw.startswith('//'):
            return 'https:' + raw
        if raw.startswith('/'):
            parsed = urlparse(product_url)
            if parsed.scheme and parsed.netloc:
                return f'{parsed.scheme}://{parsed.netloc}{raw}'
        return raw
