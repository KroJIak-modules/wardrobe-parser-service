from app.adapters.base import ShopifyCatalogAdapter


class ArchivedV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "archived__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
