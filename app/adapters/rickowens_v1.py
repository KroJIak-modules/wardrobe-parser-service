from app.adapters.base import ShopifyCatalogAdapter


class RickowensV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "rickowens__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
