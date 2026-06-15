from app.adapters.base import ShopifyCatalogAdapter


class RemnantsvintageV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "remnantsvintage__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
