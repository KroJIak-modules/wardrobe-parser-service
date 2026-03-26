"""
Data access layer - repositories for all entities.
"""

from app.repositories.base import BaseRepository
from app.repositories.parser_job import ParserJobRepository
from app.repositories.parser_product import ParserProductRepository
from app.repositories.parser_source import (
    ParserSourceRepository,
    ParserProductFingerprintRepository,
)
from app.repositories.parser_category import (
    ParserCategoryRepository,
    ParserCategoryKeywordRepository,
)

__all__ = [
    "BaseRepository",
    "ParserJobRepository",
    "ParserProductRepository",
    "ParserSourceRepository",
    "ParserProductFingerprintRepository",
    "ParserCategoryRepository",
    "ParserCategoryKeywordRepository",
]
