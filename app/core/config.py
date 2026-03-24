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
