from app.adapters.base import ShopifyCatalogAdapter


class DriewgarmentsV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "driewgarments__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
