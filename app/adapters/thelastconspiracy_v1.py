from app.adapters.base import ShopifyCatalogAdapter


class ThelastconspiracyV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "thelastconspiracy__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
