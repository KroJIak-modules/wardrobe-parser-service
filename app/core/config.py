from pathlib import Path
from typing import Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


_env_file = Path.cwd().parent.parent / ".env"


class Settings(BaseSettings):
    database_url: Optional[str] = Field(default=None, env="DATABASE_URL")
    postgres_user: str = Field(default="postgres", env="POSTGRES_USER")
    postgres_password: str = Field(default="", env="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="localhost", env="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, env="POSTGRES_PORT")
    postgres_db: str = Field(default="wardrobe", env="POSTGRES_DB")
    cors_allowed_origins: str = Field(default="", env="CORS_ALLOWED_ORIGINS")
    backend_base_url: str = Field(default="http://backend:8000", env="BACKEND_BASE_URL")
    service_token: str = Field(default="", env="SERVICE_TOKEN")
    sync_interval_sec: int = Field(default=60, env="SERVICE_SYNC_INTERVAL_SEC")
    sync_batch_size: int = Field(default=50, env="SERVICE_SYNC_BATCH_SIZE")
    request_timeout_sec: int = Field(default=15, env="SERVICE_REQUEST_TIMEOUT_SEC")
    enabled_sites: str = Field(default="example", env="SERVICE_ENABLED_SITES")
    example_site_url: str = Field(default="https://example.com", env="EXAMPLE_SITE_URL")
    example_site_use_fixture: bool = Field(default=True, env="EXAMPLE_SITE_USE_FIXTURE")

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
