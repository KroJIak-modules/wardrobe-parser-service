from __future__ import annotations

from app.adapters.contracts import StrategyContext


class ShopifyJsonStrategy:
    name = 'shopify_json'

    def run(self, context: StrategyContext) -> list[dict]:
        fixtures = context.source.source_config.get('strategy_payloads', {}).get(self.name, [])
        return fixtures if isinstance(fixtures, list) else []
