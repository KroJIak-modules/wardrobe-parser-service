from app.adapters.base import ShopifyCatalogAdapter


class PrayinggV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "prayingg__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
