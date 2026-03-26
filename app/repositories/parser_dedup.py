"""Repository for dedup candidate moderation decisions."""

from typing import Optional

from sqlalchemy.orm import Session

from app.models import ParserDedupDecision
from app.repositories.base import BaseRepository


class ParserDedupDecisionRepository(BaseRepository[ParserDedupDecision]):
    """Data access for parser_dedup_decision table."""

    def __init__(self, session: Session):
        super().__init__(session, ParserDedupDecision)

    def get_by_pair_key(self, pair_key: str) -> Optional[ParserDedupDecision]:
        return self.query().filter(ParserDedupDecision.pair_key == pair_key).first()
