from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from app.adapters.contracts import SiteAdapter, SourceContext


class JadedldnV1Adapter:
    adapter_key = 'jadedldn__v1'
    allowed_strategies = ('shopify_json', 'shopify_js', 'browser_export')

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        raw_urls = context.source_config.get('visible_catalog_set', [])
        if not isinstance(raw_urls, list):
            return []
        return [str(url).strip() for url in raw_urls if str(url).strip()]

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

        normalized = {
            'url': url,
            'handle': handle,
            'title': title,
            'price': price,
            'currency': currency,
            'weight_grams': weight_grams,
            'variants': variants,
        }
        return normalized

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
        if weight_grams is None or weight_grams <= Decimal('0'):
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
