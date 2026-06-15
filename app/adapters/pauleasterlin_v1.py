from app.adapters.base import ShopifyCatalogAdapter


class PauleasterlinV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "pauleasterlin__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
