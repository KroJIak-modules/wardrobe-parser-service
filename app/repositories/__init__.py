"""
Data access layer - repositories for all entities.
"""

from app.repositories.base import BaseRepository
from app.repositories.catalog.product_repository import ParserProductRepository
from app.repositories.job_repository import ParserJobRepository
from app.repositories.source_repository import ParserSourceRepository
from app.repositories.parser_category import (
    ParserCategoryRepository,
    ParserCategoryKeywordRepository,
)
from app.repositories.parser_dedup import ParserDedupDecisionRepository
from app.repositories.parser_image import ParserImageAssetRepository
from app.repositories.weight_settings import (
    ParserWeightRuleRepository,
    ParserWeightKeywordRepository,
)
from app.repositories.pricing_settings import ParserPricingSettingsRepository
from app.repositories.pricing_suppliers import ParserSupplierRepository

__all__ = [
    "BaseRepository",
    "ParserJobRepository",
    "ParserProductRepository",
    "ParserSourceRepository",
    "ParserCategoryRepository",
    "ParserCategoryKeywordRepository",
    "ParserDedupDecisionRepository",
    "ParserImageAssetRepository",
    "ParserWeightRuleRepository",
    "ParserWeightKeywordRepository",
    "ParserPricingSettingsRepository",
    "ParserSupplierRepository",
]
