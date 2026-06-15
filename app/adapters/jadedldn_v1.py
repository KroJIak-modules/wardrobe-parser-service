from app.adapters.base import ShopifyCatalogAdapter


class JadedldnV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "jadedldn__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
