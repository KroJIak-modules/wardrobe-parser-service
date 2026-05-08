from app.adapters.contracts import Strategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Strategy] = {}

    def register(self, strategy: Strategy) -> None:
        self._items[strategy.name] = strategy

    def get(self, name: str) -> Strategy:
        if name not in self._items:
            raise KeyError(f'Unknown strategy: {name}')
        return self._items[name]
