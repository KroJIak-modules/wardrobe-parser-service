from fastapi import APIRouter, HTTPException, Query

from app.adapters.jadedldn_v1 import JadedldnV1Adapter
from app.adapters.racerworldwide_v1 import RacerworldwideV1Adapter
from app.adapters.registry import AdapterRegistry
from app.core.config import settings
from app.core.exceptions import ConfigError
from app.repositories.source_repository import SourceRepository
from app.schemas.run_report import SourceRunReport
from app.services.source_run_service import SourceRunService
from app.services.weight_rules_client import WeightRulesClient
from app.strategies.browser_export import BrowserExportStrategy
from app.strategies.registry import StrategyRegistry
from app.strategies.shopify_js import ShopifyJsStrategy
from app.strategies.shopify_json import ShopifyJsonStrategy

router = APIRouter(prefix='/sync', tags=['sync'])


def _build_service() -> SourceRunService:
    source_repo = SourceRepository()

    adapter_registry = AdapterRegistry()
    adapter_registry.register(JadedldnV1Adapter())
    adapter_registry.register(RacerworldwideV1Adapter())

    strategy_registry = StrategyRegistry()
    strategy_registry.register(ShopifyJsonStrategy())
    strategy_registry.register(ShopifyJsStrategy())
    strategy_registry.register(BrowserExportStrategy())

    weight_rules_client = WeightRulesClient(backend_base_url=settings.backend_base_url)
    return SourceRunService(source_repo, adapter_registry, strategy_registry, weight_rules_client=weight_rules_client)


@router.post('/sources/{source_key}/run', response_model=SourceRunReport)
def run_source(source_key: str, dry_run: bool = Query(default=False)) -> SourceRunReport:
    svc = _build_service()
    try:
        return svc.run(source_key=source_key, dry_run=dry_run)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
