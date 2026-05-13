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
from app.adapters.prayingg_v1 import PrayinggV1Adapter
from app.adapters.fourtwofour_v1 import FourtwofourV1Adapter
from app.adapters.remnantsvintage_v1 import RemnantsvintageV1Adapter
from app.adapters.misssixty_v1 import MisssixtyV1Adapter
from app.adapters.hlorenzo_v1 import HlorenzoV1Adapter
from app.adapters.simonerocha_v1 import SimonerochaV1Adapter
from app.adapters.orimono_v1 import OrimonoV1Adapter
from app.adapters.pauleasterlin_v1 import PauleasterlinV1Adapter
from app.adapters.driewgarments_v1 import DriewgarmentsV1Adapter
from app.adapters.junalyx_v1 import JunalyxV1Adapter
from app.adapters.archived_v1 import ArchivedV1Adapter
from app.adapters.dolcevitahub_v1 import DolcevitahubV1Adapter
from app.adapters.store_backlash_v1 import StoreBacklashV1Adapter
from app.adapters.vinted_v1 import VintedV1Adapter
from app.adapters.grailed_v1 import GrailedV1Adapter
from app.adapters.newrock_v1 import NewrockV1Adapter
from app.adapters.rickowens_v1 import RickowensV1Adapter
from app.adapters.goat_v1 import GoatV1Adapter
from app.adapters.intlprotocolindex_v1 import IntlprotocolindexV1Adapter
from app.adapters.registry import AdapterRegistry
from app.core.config import settings
from app.repositories.source_repository import SourceRepository
from app.services.run_report_markdown_service import RunReportMarkdownService
from app.services.source_run_service import SourceRunService
from app.services.weight_rules_client import WeightRulesClient
from app.strategies.registry import StrategyRegistry
from app.strategies.shopify_browser_extension import ShopifyBrowserExtensionStrategy
from app.strategies.shopify_js import ShopifyJsStrategy
from app.strategies.shopify_json import ShopifyJsonStrategy
from app.strategies.store_backlash_colorme import StoreBacklashColormeStrategy
from app.strategies.vinted_jsonld import VintedJsonLdStrategy
from app.strategies.grailed_algolia_jsonld import GrailedAlgoliaJsonLdStrategy
from app.strategies.goat_browser_extension import GoatBrowserExtensionStrategy
from app.strategies.intl_protocol_index_cafe24 import IntlProtocolIndexCafe24Strategy


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
        adapter_registry.register(PrayinggV1Adapter())
        adapter_registry.register(FourtwofourV1Adapter())
        adapter_registry.register(RemnantsvintageV1Adapter())
        adapter_registry.register(MisssixtyV1Adapter())
        adapter_registry.register(HlorenzoV1Adapter())
        adapter_registry.register(SimonerochaV1Adapter())
        adapter_registry.register(OrimonoV1Adapter())
        adapter_registry.register(PauleasterlinV1Adapter())
        adapter_registry.register(DriewgarmentsV1Adapter())
        adapter_registry.register(JunalyxV1Adapter())
        adapter_registry.register(ArchivedV1Adapter())
        adapter_registry.register(DolcevitahubV1Adapter())
        adapter_registry.register(StoreBacklashV1Adapter())
        adapter_registry.register(VintedV1Adapter())
        adapter_registry.register(GrailedV1Adapter())
        adapter_registry.register(NewrockV1Adapter())
        adapter_registry.register(RickowensV1Adapter())
        adapter_registry.register(GoatV1Adapter())
        adapter_registry.register(IntlprotocolindexV1Adapter())

        strategy_registry = StrategyRegistry()
        strategy_registry.register(ShopifyJsonStrategy())
        strategy_registry.register(ShopifyJsStrategy())
        strategy_registry.register(ShopifyBrowserExtensionStrategy())
        strategy_registry.register(StoreBacklashColormeStrategy())
        strategy_registry.register(VintedJsonLdStrategy())
        strategy_registry.register(GrailedAlgoliaJsonLdStrategy())
        strategy_registry.register(GoatBrowserExtensionStrategy())
        strategy_registry.register(IntlProtocolIndexCafe24Strategy())

        weight_rules_client = WeightRulesClient(backend_base_url=settings.backend_base_url)
        return SourceRunService(
            SourceRepository(),
            adapter_registry,
            strategy_registry,
            markdown_report_service=RunReportMarkdownService(reports_root=settings.reports_root),
            weight_rules_client=weight_rules_client,
        )
