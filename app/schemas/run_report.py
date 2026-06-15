from pydantic import BaseModel, Field

from app.domain.statuses import SourceRunStatus


class StrategyAttempt(BaseModel):
    strategy: str
    success: bool
    raw_count: int = 0
    parsed_count: int = 0
    error: str | None = None
    diagnostics: dict[str, int | float | str] = Field(default_factory=dict)


class SourceRunReport(BaseModel):
    source_key: str
    adapter_key: str
    dry_run: bool = False
    visible_catalog_products: int = 0
    parsed_visible_products: int = 0
    visible_coverage: float = 0.0
    status: SourceRunStatus = SourceRunStatus.PENDING
    attempts: list[StrategyAttempt] = Field(default_factory=list)
    quarantined_urls: list[str] = Field(default_factory=list)
    aggregated_status_reasons: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    total_found_products: int = 0
    total_valid_products: int = 0
    valid_products: list[dict] = Field(default_factory=list)
    unavailable_products: list[dict] = Field(default_factory=list)
    duration_sec: float = 0.0
    weight_source_stats: dict[str, int] = Field(default_factory=dict)
