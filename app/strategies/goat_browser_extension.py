from __future__ import annotations

from app.adapters.contracts import StrategyContext
from app.strategies.shopify_browser_extension import ShopifyBrowserExtensionStrategy


class GoatBrowserExtensionStrategy:
    """
    GOAT-specific browser strategy.
    Reuses hardened browser-runner flow from shopify_browser_extension but
    emits its own strategy name for isolated per-site config/retries/logging.
    """

    name = "goat_browser_extension"

    def run(self, context: StrategyContext) -> list[dict]:
        delegate = ShopifyBrowserExtensionStrategy()
        original_name = delegate.name
        try:
            # Keep logs/diagnostics under goat strategy namespace.
            delegate.name = self.name
            return delegate.run(context)
        finally:
            delegate.name = original_name

