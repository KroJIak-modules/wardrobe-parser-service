from app.adapters.base import ShopifyCatalogAdapter


class HlorenzoV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "hlorenzo__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
