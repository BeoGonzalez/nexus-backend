from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "cart-service"
    PORT: int = 8000
    DEBUG: bool = False

    REDIS_URL: str = "redis://redis:6379/0"
    CART_TTL_SECONDS: int = 60 * 60 * 24 * 7  # 7 días de persistencia en Redis
    CATALOG_SERVICE_URL: str = "http://catalog-service:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()

