from __future__ import annotations

from app.adapters.essxnyc_v1 import EssxnycV1Adapter
from app.adapters.jadedldn_v1 import JadedldnV1Adapter
from app.adapters.nofaithstudios_v1 import NofaithstudiosV1Adapter
from app.adapters.paradoxeparis_v1 import ParadoxeparisV1Adapter
from app.adapters.juliusgarden_v1 import JuliusgardenV1Adapter
from app.adapters.professore_v1 import ProfessoreV1Adapter
from app.adapters.thelastconspiracy_v1 import ThelastconspiracyV1Adapter
from app.adapters.racerworldwide_v1 import RacerworldwideV1Adapter
from app.adapters.fourteenthaddiction_v1 import FourteenthaddictionV1Adapter
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
        adapter_registry.register(EssxnycV1Adapter())
        adapter_registry.register(JadedldnV1Adapter())
        adapter_registry.register(NofaithstudiosV1Adapter())
        adapter_registry.register(ParadoxeparisV1Adapter())
        adapter_registry.register(JuliusgardenV1Adapter())
        adapter_registry.register(ProfessoreV1Adapter())
        adapter_registry.register(ThelastconspiracyV1Adapter())
        adapter_registry.register(RacerworldwideV1Adapter())
        adapter_registry.register(FourteenthaddictionV1Adapter())

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
