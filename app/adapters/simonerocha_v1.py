from app.adapters.base import ShopifyCatalogAdapter


class SimonerochaV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "simonerocha__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
