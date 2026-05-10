from __future__ import annotations

from app.adapters.jadedldn_v1 import JadedldnV1Adapter
from app.adapters.registry import AdapterRegistry
from app.core.config import settings
from app.repositories.source_repository import SourceRepository
from app.services.run_report_markdown_service import RunReportMarkdownService
from app.services.source_run_service import SourceRunService
from app.services.weight_rules_client import WeightRulesClient
from app.strategies.registry import StrategyRegistry
from app.strategies.shopify_js import ShopifyJsStrategy
from app.strategies.shopify_json import ShopifyJsonStrategy


class SourceRunServiceFactory:
    def build(self) -> SourceRunService:
        adapter_registry = AdapterRegistry()
        adapter_registry.register(JadedldnV1Adapter())

        strategy_registry = StrategyRegistry()
        strategy_registry.register(ShopifyJsonStrategy())
        strategy_registry.register(ShopifyJsStrategy())

        weight_rules_client = WeightRulesClient(backend_base_url=settings.backend_base_url)
        return SourceRunService(
            SourceRepository(),
            adapter_registry,
            strategy_registry,
            markdown_report_service=RunReportMarkdownService(reports_root=settings.reports_root),
            weight_rules_client=weight_rules_client,
        )
