from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "orders-service"
    PORT: int = 8000
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://nexus:nexus123@postgres:5432/nexus_orders"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5

    CATALOG_SERVICE_URL: str = "http://catalog-service:8000"
    # Eventos de dominio -> topic SNS (vacio = no se publica; desarrollo local sin AWS)
    EVENTS_TOPIC_ARN: str = ""
    AWS_REGION: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()

