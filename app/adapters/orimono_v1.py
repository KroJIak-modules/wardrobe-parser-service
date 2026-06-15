from app.adapters.base import ShopifyCatalogAdapter


class OrimonoV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "orimono__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
