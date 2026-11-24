from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "recommendations-service"
    PORT: int = 8000
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://nexus:nexus123@postgres:5432/nexus_recommendations"
    REDIS_URL: str = "redis://redis:6379/1"

    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = "nexus-catalog"
    PINECONE_NAMESPACE: str = "nexus_chile"


@lru_cache
def get_settings() -> Settings:
    return Settings()

