from app.adapters.base import ShopifyCatalogAdapter


class ParadoxeparisV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "paradoxeparis__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
