from app.adapters.base import PassiveCatalogAdapter


class GoatV1Adapter(PassiveCatalogAdapter):
    adapter_key = "goat__v1"
    allowed_strategies = ("goat_browser_extension",)
