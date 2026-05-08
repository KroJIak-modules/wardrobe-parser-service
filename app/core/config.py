from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    service_name: str = 'wardrobe-parser-service-v2'
    cors_allowed_origins: str = '*'


settings = Settings()
