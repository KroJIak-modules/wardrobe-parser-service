from app.adapters.base import ShopifyCatalogAdapter


class JunalyxV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "junalyx__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
