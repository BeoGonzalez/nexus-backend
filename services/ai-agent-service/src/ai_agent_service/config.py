from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SERVICE_NAME: str = "ai-agent-service"
    PORT: int = 8000
    DEBUG: bool = False

    REDIS_URL: str = "redis://redis:6379/2"
    CATALOG_SERVICE_URL: str = "http://catalog-service:8000"

    GROQ_API_KEY: str = ""
    GROQ_MODEL_NAME: str = "openai/gpt-oss-120b"
    GROQ_TEMPERATURE: float = 0.1

    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = "nexus-games"
    PINECONE_NAMESPACE: str = "catalog"

    EMBEDDING_MODEL_NAME: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # LLM04 Supply Chain: commit exacto del modelo en HuggingFace (no "main"): un push al repo no entra sin revisión.
    EMBEDDING_MODEL_REVISION: str = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    EMBEDDING_DIMENSIONS: int = 384
    VECTOR_SEARCH_TOP_K: int = 5

    WIKIPEDIA_LANG: str = "es"
    WIKIPEDIA_TOP_K: int = 1
    WIKIPEDIA_MAX_CHARS: int = 400

    TAVILY_API_KEY: str = ""
    TAVILY_MAX_RESULTS: int = 3

    CHEAPSHARK_ENABLED: bool = True
    CHEAPSHARK_USD_CLP_RATE: float = 950.0

    ENABLE_CREWAI_ORCHESTRATION: bool = False
    # LLM04: el repo de Laya incluye código Python y no fija revisión; desactivado salvo decisión explícita
    # (sin él se usan las heurísticas deterministas del adaptador).
    ENABLE_LAYA_DECISION_ENGINE: bool = False
    LAYA_MODEL_NAME: str = "convaiinnovations/laya"

    # SMTP / Gmail (para envío de ofertas y resúmenes por correo desde el chat)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "Nexus Digital Store 🎮"
    GMAIL_USER: str = ""
    GMAIL_APP_PASSWORD: str = ""

    # ------------------------------------------------------------------ Guardrails (OWASP LLM Top 10 2026)
    # Kill switch (Agentic v2 §3.3.8): false -> el asistente responde 503 sin invocar al modelo.
    ASSISTANT_ENABLED: bool = True
    # LLM06 Unbounded Consumption: cuotas por usuario (sub del JWT) y techo global por pod.
    LLM_REQUESTS_PER_MINUTE: int = 10
    LLM_REQUESTS_PER_DAY: int = 200
    LLM_MAX_CONCURRENT_STREAMS: int = 1
    LLM_GLOBAL_REQUESTS_PER_DAY: int = 5000
    LLM_MAX_TOKENS: int = 1024
    LLM_REQUEST_TIMEOUT_SECONDS: float = 30.0
    LLM_MAX_RETRIES: int = 1
    LLM_STREAM_TIMEOUT_SECONDS: float = 60.0
    LLM_MAX_OUTPUT_CHARS: int = 6000
    # Memoria: hilos máximos por pod (LRU) y envíos de correo por usuario y hora (LLM03).
    ASSISTANT_MAX_THREADS: int = 5000
    ASSISTANT_EMAILS_PER_HOUR: int = 3

    # LangSmith Tracing & Observability
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "nexus-ai"

    @model_validator(mode="after")
    def ensure_valid_keys(self) -> "Settings":
        # Una key vacia = no configurada: nunca se sustituye por una credencial embebida.
        valid_model_name = "openai/gpt-oss-120b"
        if not self.GROQ_MODEL_NAME or self.GROQ_MODEL_NAME in ("openai/gpt-oss-20b", "your-groq-model-name"):
            self.GROQ_MODEL_NAME = valid_model_name
        # LLM09: no se recuperan más vecinos de los necesarios (minimum-scope k-NN).
        self.VECTOR_SEARCH_TOP_K = max(1, min(self.VECTOR_SEARCH_TOP_K, 10))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

