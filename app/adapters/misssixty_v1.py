from app.adapters.base import ShopifyCatalogAdapter


class MisssixtyV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "misssixty__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
