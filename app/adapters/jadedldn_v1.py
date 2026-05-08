from app.adapters.contracts import SiteAdapter, SourceContext


class JadedldnV1Adapter:
    adapter_key = 'jadedldn__v1'
    allowed_strategies = ('noop',)

    def discover_visible_catalog(self, context: SourceContext) -> list[str]:
        return []

    def normalize_product(self, raw_product: dict) -> dict:
        return {
            'url': raw_product.get('url'),
            'price': raw_product.get('price'),
            'currency': raw_product.get('currency'),
            'weight_grams': raw_product.get('weight_grams'),
        }

    def validate_product(self, normalized_product: dict) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if not normalized_product.get('url'):
            reasons.append('missing_url')
        if not normalized_product.get('price'):
            reasons.append('missing_price')
        if not normalized_product.get('currency'):
            reasons.append('missing_currency')
        if normalized_product.get('weight_grams') is None:
            reasons.append('missing_weight')
        return (len(reasons) == 0, reasons)
