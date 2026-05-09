from pydantic import BaseModel, Field

from app.domain.statuses import SourceRunStatus


class StrategyAttempt(BaseModel):
    strategy: str
    success: bool
    raw_count: int = 0
    parsed_count: int = 0
    error: str | None = None


class SourceRunReport(BaseModel):
    source_id: int
    source_key: str
    adapter_key: str
    dry_run: bool = False
    visible_catalog_products: int = 0
    parsed_visible_products: int = 0
    visible_coverage: float = 0.0
    status: SourceRunStatus = SourceRunStatus.PENDING
    attempts: list[StrategyAttempt] = Field(default_factory=list)
    quarantined_urls: list[str] = Field(default_factory=list)
    aggregated_unavailable_reasons: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
