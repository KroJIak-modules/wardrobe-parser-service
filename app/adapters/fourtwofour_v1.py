from app.adapters.base import ShopifyCatalogAdapter


class FourtwofourV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "fourtwofour__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
