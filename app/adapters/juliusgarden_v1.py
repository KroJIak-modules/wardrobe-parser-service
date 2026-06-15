from app.adapters.base import ShopifyCatalogAdapter


class JuliusgardenV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "juliusgarden__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
