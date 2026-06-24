from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    service_name: str = 'wardrobe-parser-service-v2'
    cors_allowed_origins: str = Field(default='*', validation_alias='CORS_ALLOWED_ORIGINS')
    backend_base_url: str = Field(default='http://backend:8000', validation_alias='BACKEND_BASE_URL')
    internal_api_token: str = Field(validation_alias='INTERNAL_API_TOKEN')
    sources_config_path: str = Field(default='config/sources.json', validation_alias='SOURCES_CONFIG_PATH')


settings = Settings()
