from app.adapters.base import ShopifyCatalogAdapter


class NewrockV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "newrock__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
