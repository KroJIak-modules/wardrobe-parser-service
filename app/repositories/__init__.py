"""
Data access layer - repositories for all entities.
"""

from app.repositories.base import BaseRepository
from app.repositories.catalog.product_repository import ParserProductRepository
from app.repositories.job_repository import ParserJobRepository
from app.repositories.source_repository import (
    ParserSourceRepository,
    ParserProductFingerprintRepository,
)
from app.repositories.parser_category import (
    ParserCategoryRepository,
    ParserCategoryKeywordRepository,
)
from app.repositories.parser_dedup import ParserDedupDecisionRepository
from app.repositories.parser_image import ParserImageAssetRepository

__all__ = [
    "BaseRepository",
    "ParserJobRepository",
    "ParserProductRepository",
    "ParserSourceRepository",
    "ParserProductFingerprintRepository",
    "ParserCategoryRepository",
    "ParserCategoryKeywordRepository",
    "ParserDedupDecisionRepository",
    "ParserImageAssetRepository",
]
