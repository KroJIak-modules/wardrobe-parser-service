from app.adapters.base import ShopifyCatalogAdapter


class DolcevitahubV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "dolcevitahub__v1"
    allowed_strategies = ("shopify_json", "shopify_js", "shopify_browser_extension")
