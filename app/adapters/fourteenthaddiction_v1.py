from app.adapters.base import ShopifyCatalogAdapter


class FourteenthaddictionV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "fourteenthaddiction__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
