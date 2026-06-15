from app.adapters.base import ShopifyCatalogAdapter


class NofaithstudiosV1Adapter(ShopifyCatalogAdapter):
    adapter_key = "nofaithstudios__v1"
    allowed_strategies = ("shopify_json", "shopify_js")
