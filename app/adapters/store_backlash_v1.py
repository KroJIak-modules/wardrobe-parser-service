from urllib.parse import parse_qs, urlparse

from app.adapters.base import PassiveCatalogAdapter


class StoreBacklashV1Adapter(PassiveCatalogAdapter):
    adapter_key = "store_backlash__v1"
    allowed_strategies = ("store_backlash_colorme",)
    allowed_currencies = frozenset({"USD", "EUR", "GBP", "JPY"})

    def _extract_handle(self, url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        pid = (parse_qs(parsed.query).get("pid") or [""])[0].strip()
        return f"pid-{pid}" if pid else ""
