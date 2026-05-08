from app.adapters.contracts import SiteAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._items: dict[str, SiteAdapter] = {}

    def register(self, adapter: SiteAdapter) -> None:
        self._items[adapter.adapter_key] = adapter

    def get(self, adapter_key: str) -> SiteAdapter:
        if adapter_key not in self._items:
            raise KeyError(f'Unknown adapter_key: {adapter_key}')
        return self._items[adapter_key]
