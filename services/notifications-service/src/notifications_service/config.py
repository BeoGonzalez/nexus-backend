from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "notifications-service"
    PORT: int = 8000
    DEBUG: bool = False

    # Cola SQS suscrita al topic SNS de eventos (order.* + user.registered). Vacia = consumidor apagado
    EVENTS_QUEUE_URL: str = ""
    AWS_REGION: str = "us-east-1"

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "Nexus Digital Store 🎮"


@lru_cache
def get_settings() -> Settings:
    return Settings()

