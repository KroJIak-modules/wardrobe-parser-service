from app.adapters.base import ShopifyCatalogAdapter


class EssxnycV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "essxnyc__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
