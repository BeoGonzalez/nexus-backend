from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "auth-service"
    PORT: int = 8000
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://nexus:nexus123@postgres:5432/nexus_auth"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5

    # Sin valor por defecto: el modo local exige un secreto explícito (fail-closed).
    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60

    COGNITO_REGION: str = "us-east-1"
    COGNITO_USER_POOL_ID: str = ""
    COGNITO_APP_CLIENT_ID: str = ""
    COGNITO_APP_CLIENT_SECRET: str = ""

    # Modo local (sin Cognito): solo para desarrollo/tests y SOLO si se activa explicitamente.
    # Sin Cognito y sin este flag, el servicio rechaza todo login (fail-closed).
    AUTH_LOCAL_MODE: bool = False
    # Emails (separados por coma) que reciben rol admin en modo local.
    LOCAL_ADMIN_EMAILS: str = ""

    # Eventos de dominio -> topic SNS (vacio = no se publica; desarrollo local sin AWS)
    EVENTS_TOPIC_ARN: str = ""
    AWS_REGION: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()

