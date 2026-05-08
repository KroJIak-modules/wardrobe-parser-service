from app.adapters.contracts import StrategyContext


class NoopStrategy:
    name = 'noop'

    def run(self, context: StrategyContext) -> list[dict]:
        return []
