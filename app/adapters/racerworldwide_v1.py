from app.adapters.base import ShopifyCatalogAdapter


class RacerworldwideV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "racerworldwide__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
