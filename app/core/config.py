from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


_service_root = Path(__file__).resolve().parents[2]
_repo_root = _service_root.parent
_env_file = _repo_root / ".env"


class Settings(BaseSettings):
    database_url: Optional[str] = Field(default=None, env="DATABASE_URL")
    postgres_user: str = Field(default="postgres", env="POSTGRES_USER")
    postgres_password: str = Field(default="", env="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="localhost", env="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, env="POSTGRES_PORT")
    postgres_db: str = Field(default="wardrobe", env="POSTGRES_DB")
    cors_allowed_origins: str = Field(default="", env="CORS_ALLOWED_ORIGINS")
    parser_sources_file: str = Field(
        default=str(_service_root / "config" / "sources.json"),
        env="PARSER_SOURCES_FILE",
    )
    parser_default_timeout_sec: float = Field(default=12.0, ge=3.0, le=120.0, env="PARSER_DEFAULT_TIMEOUT_SEC")
    parser_default_max_products: int = Field(default=5000, ge=1, le=100000, env="PARSER_DEFAULT_MAX_PRODUCTS")
    parser_default_sample_products: int = Field(default=5, ge=1, le=1000, env="PARSER_DEFAULT_SAMPLE_PRODUCTS")
    parser_default_parallel_workers: int = Field(default=12, ge=1, le=64, env="PARSER_DEFAULT_PARALLEL_WORKERS")
    parser_default_max_retries: int = Field(default=2, ge=0, le=10, env="PARSER_DEFAULT_MAX_RETRIES")
    parser_default_retry_backoff_sec: float = Field(
        default=0.4,
        ge=0.0,
        le=5.0,
        env="PARSER_DEFAULT_RETRY_BACKOFF_SEC",
    )
    parser_default_second_pass_enabled: bool = Field(
        default=True,
        env="PARSER_DEFAULT_SECOND_PASS_ENABLED",
    )
    parser_default_second_pass_timeout_sec: float = Field(
        default=20.0,
        ge=3.0,
        le=240.0,
        env="PARSER_DEFAULT_SECOND_PASS_TIMEOUT_SEC",
    )
    parser_empty_discovery_source_retries: int = Field(
        default=1,
        ge=0,
        le=5,
        env="PARSER_EMPTY_DISCOVERY_SOURCE_RETRIES",
    )
    parser_empty_discovery_retry_backoff_sec: float = Field(
        default=1.5,
        ge=0.0,
        le=30.0,
        env="PARSER_EMPTY_DISCOVERY_RETRY_BACKOFF_SEC",
    )
    parser_default_error_details_limit: int = Field(
        default=200,
        ge=1,
        le=5000,
        env="PARSER_DEFAULT_ERROR_DETAILS_LIMIT",
    )
    parser_discovery_safety_limit: int = Field(
        default=2000,
        ge=100,
        le=20000,
        env="PARSER_DISCOVERY_SAFETY_LIMIT",
    )
    parser_discovery_collections_safety_limit: int = Field(
        default=300,
        ge=10,
        le=5000,
        env="PARSER_DISCOVERY_COLLECTIONS_SAFETY_LIMIT",
    )
    parser_discovery_sitemap_workers: int = Field(
        default=4,
        ge=1,
        le=16,
        env="PARSER_DISCOVERY_SITEMAP_WORKERS",
    )
    parser_discovery_fail_fast_on_rate_limit: bool = Field(
        default=False,
        env="PARSER_DISCOVERY_FAIL_FAST_ON_RATE_LIMIT",
    )
    parser_recover_from_existing_urls_enabled: bool = Field(
        default=True,
        env="PARSER_RECOVER_FROM_EXISTING_URLS_ENABLED",
    )
    parser_recovery_network_enabled: bool = Field(
        default=False,
        env="PARSER_RECOVERY_NETWORK_ENABLED",
    )
    parser_recovery_parallel_workers: int = Field(
        default=96,
        ge=1,
        le=256,
        env="PARSER_RECOVERY_PARALLEL_WORKERS",
    )
    parser_recovery_timeout_sec: float = Field(
        default=6.0,
        ge=1.0,
        le=120.0,
        env="PARSER_RECOVERY_TIMEOUT_SEC",
    )
    parser_recovery_max_retries: int = Field(
        default=0,
        ge=0,
        le=10,
        env="PARSER_RECOVERY_MAX_RETRIES",
    )
    parser_recovery_retry_backoff_sec: float = Field(
        default=0.2,
        ge=0.0,
        le=10.0,
        env="PARSER_RECOVERY_RETRY_BACKOFF_SEC",
    )
    parser_recovery_second_pass_timeout_sec: float = Field(
        default=8.0,
        ge=1.0,
        le=240.0,
        env="PARSER_RECOVERY_SECOND_PASS_TIMEOUT_SEC",
    )
    parser_shopify_page_size: int = Field(
        default=250,
        ge=10,
        le=250,
        env="PARSER_SHOPIFY_PAGE_SIZE",
    )
    parser_discovery_warning_items_limit: int = Field(
        default=20,
        ge=1,
        le=500,
        env="PARSER_DISCOVERY_WARNING_ITEMS_LIMIT",
    )
    parser_second_pass_max_workers: int = Field(
        default=8,
        ge=1,
        le=64,
        env="PARSER_SECOND_PASS_MAX_WORKERS",
    )
    parser_second_pass_min_backoff_sec: float = Field(
        default=0.5,
        ge=0.0,
        le=10.0,
        env="PARSER_SECOND_PASS_MIN_BACKOFF_SEC",
    )
    parser_rate_limit_min_cooldown_sec: float = Field(
        default=1.0,
        ge=0.0,
        le=60.0,
        env="PARSER_RATE_LIMIT_MIN_COOLDOWN_SEC",
    )
    parser_rate_limit_jitter_sec: float = Field(
        default=0.15,
        ge=0.0,
        le=5.0,
        env="PARSER_RATE_LIMIT_JITTER_SEC",
    )
    parser_timeout_cooldown_sec: float = Field(
        default=0.25,
        ge=0.0,
        le=30.0,
        env="PARSER_TIMEOUT_COOLDOWN_SEC",
    )
    parser_source_timeout_sec: float = Field(
        default=180.0,
        ge=30.0,
        le=3600.0,
        env="PARSER_SOURCE_TIMEOUT_SEC",
    )
    parser_circuit_breaker_429_threshold: int = Field(
        default=5,
        ge=1,
        le=200,
        env="PARSER_CIRCUIT_BREAKER_429_THRESHOLD",
    )
    parser_circuit_breaker_max_penalty: int = Field(
        default=3,
        ge=1,
        le=8,
        env="PARSER_CIRCUIT_BREAKER_MAX_PENALTY",
    )
    parser_circuit_breaker_recovery_successes: int = Field(
        default=30,
        ge=1,
        le=5000,
        env="PARSER_CIRCUIT_BREAKER_RECOVERY_SUCCESSES",
    )
    parser_circuit_breaker_pause_sec: float = Field(
        default=3.0,
        ge=0.0,
        le=120.0,
        env="PARSER_CIRCUIT_BREAKER_PAUSE_SEC",
    )
    parser_sync_max_sources: int = Field(
        default=0,
        ge=0,
        le=200,
        env="PARSER_SYNC_MAX_SOURCES",
    )
    parser_sync_source_workers: int = Field(
        default=4,
        ge=1,
        le=16,
        env="PARSER_SYNC_SOURCE_WORKERS",
    )
    parser_sync_period_minutes: int = Field(
        default=300,
        ge=15,
        le=10080,
        env="PARSER_SYNC_PERIOD_MINUTES",
    )
    parser_job_stale_minutes: int = Field(
        default=180,
        ge=5,
        le=10080,
        env="PARSER_JOB_STALE_MINUTES",
    )
    image_proxy_timeout_sec: float = Field(default=10.0, ge=1.0, le=60.0, env="IMAGE_PROXY_TIMEOUT_SEC")
    image_proxy_max_bytes: int = Field(default=8_000_000, ge=100_000, le=50_000_000, env="IMAGE_PROXY_MAX_BYTES")
    image_cache_max_age_sec: int = Field(default=86400, ge=0, le=604800, env="IMAGE_CACHE_MAX_AGE_SEC")
    image_rate_limit_per_minute: int = Field(default=120, ge=10, le=5000, env="IMAGE_RATE_LIMIT_PER_MINUTE")
    preview_js_price_cents_threshold: int = Field(
        default=1000,
        ge=0,
        le=1_000_000,
        env="PREVIEW_JS_PRICE_CENTS_THRESHOLD",
    )
    preview_js_price_cents_divisor: int = Field(
        default=100,
        ge=1,
        le=10000,
        env="PREVIEW_JS_PRICE_CENTS_DIVISOR",
    )
    dedup_scan_limit: int = Field(default=2000, ge=10, le=100000, env="DEDUP_SCAN_LIMIT")
    dedup_score_threshold: float = Field(default=0.55, ge=0.0, le=1.0, env="DEDUP_SCORE_THRESHOLD")
    dedup_title_match_weight: float = Field(default=0.55, ge=0.0, le=1.0, env="DEDUP_TITLE_MATCH_WEIGHT")
    dedup_vendor_match_weight: float = Field(default=0.25, ge=0.0, le=1.0, env="DEDUP_VENDOR_MATCH_WEIGHT")
    dedup_price_close_weight: float = Field(default=0.15, ge=0.0, le=1.0, env="DEDUP_PRICE_CLOSE_WEIGHT")
    dedup_handle_match_weight: float = Field(default=0.2, ge=0.0, le=1.0, env="DEDUP_HANDLE_MATCH_WEIGHT")
    dedup_price_diff_ratio_limit: float = Field(
        default=0.08,
        ge=0.0,
        le=1.0,
        env="DEDUP_PRICE_DIFF_RATIO_LIMIT",
    )
    dedup_score_cap: float = Field(default=0.99, ge=0.0, le=1.0, env="DEDUP_SCORE_CAP")
    dedup_candidates_default_limit: int = Field(
        default=30,
        ge=1,
        le=1000,
        env="DEDUP_CANDIDATES_DEFAULT_LIMIT",
    )
    dedup_candidates_max_limit: int = Field(
        default=200,
        ge=1,
        le=5000,
        env="DEDUP_CANDIDATES_MAX_LIMIT",
    )
    api_pagination_default_limit: int = Field(default=20, ge=1, le=500, env="API_PAGINATION_DEFAULT_LIMIT")
    api_pagination_max_limit: int = Field(default=200, ge=1, le=5000, env="API_PAGINATION_MAX_LIMIT")
    sync_jobs_history_max_limit: int = Field(default=100, ge=1, le=5000, env="SYNC_JOBS_HISTORY_MAX_LIMIT")
    uploads_dir: str = Field(default="/app/uploads", env="UPLOADS_DIR")
    uploads_allowed_extensions: str = Field(
        default=".jpg,.jpeg,.png,.webp,.gif",
        env="UPLOADS_ALLOWED_EXTENSIONS",
    )
    manual_source_name: str = Field(default="Manual Upload", env="MANUAL_SOURCE_NAME")
    manual_source_url: str = Field(default="https://manual.local", env="MANUAL_SOURCE_URL")
    manual_source_parser_type: str = Field(default="custom", env="MANUAL_SOURCE_PARSER_TYPE")
    manual_product_vendor_default: str = Field(default="Manual", env="MANUAL_PRODUCT_VENDOR_DEFAULT")

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        if not self.database_url:
            url = (
                f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
            object.__setattr__(self, "database_url", url)
        return self

    class Config:
        env_file = str(_env_file) if _env_file.exists() else None
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
