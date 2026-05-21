from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

from app.adapters.contracts import SourceContext


class StoreBacklashV1Adapter:
    adapter_key = 'store_backlash__v1'
    allowed_strategies = ('store_backlash_colorme',)

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        # Strategy can self-discover from sitemap when candidates are empty.
        return []

    def normalize_product(self, raw_product: dict) -> dict:
        url = str(raw_product.get('url') or '').strip()
        handle = str(raw_product.get('handle') or '').strip() or self._extract_handle(url)
        variants = raw_product.get('variants')
        if not isinstance(variants, list) or not variants:
            variants = [{'title': 'default', 'available': False}]
        images = raw_product.get('images')
        image_url = str(raw_product.get('image_url') or '').strip()
        if not image_url and isinstance(images, list) and images:
            image_url = str(images[0]).strip()
        return {
            'url': url,
            'handle': handle,
            'title': str(raw_product.get('title') or '').strip(),
            'product_type': str(raw_product.get('product_type') or '').strip(),
            'tags': raw_product.get('tags') if isinstance(raw_product.get('tags'), list) else [],
            'price': self._to_decimal(raw_product.get('price')),
            'currency': str(raw_product.get('currency') or '').strip().upper(),
            'weight_grams': self._to_decimal(raw_product.get('weight_grams')),
            'image_url': image_url,
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
        currency = str(normalized_product.get('currency') or '').strip().upper()
        if not currency or len(currency) != 3:
            reasons.append('missing_currency')
        allowed = {'USD', 'EUR', 'GBP', 'JPY'}
        if currency and currency not in allowed:
            reasons.append('unsupported_currency')
        weight_grams = normalized_product.get('weight_grams')
        weight_source = str(normalized_product.get('weight_source') or '').strip().lower()
        if weight_source == 'missing' or weight_grams is None or weight_grams <= Decimal('0'):
            reasons.append('missing_weight')
        variants = normalized_product.get('variants')
        if not isinstance(variants, list) or not variants:
            reasons.append('missing_variants')
        return (len(reasons) == 0, reasons)

    @staticmethod
    def _to_decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _extract_handle(url: str) -> str:
        parsed = urlparse(str(url or '').strip())
        pid = (parse_qs(parsed.query).get('pid') or [''])[0].strip()
        return f'pid-{pid}' if pid else ''
