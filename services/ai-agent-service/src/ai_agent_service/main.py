from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI

from ai_agent_service.config import get_settings
from ai_agent_service.presentation.router import router as assistant_router
from nexus_core.infrastructure.logging import setup_service_logging
from nexus_core.presentation.security import configure_service

settings = get_settings()
logger = setup_service_logging(settings.SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s on port %d...", settings.SERVICE_NAME, settings.PORT)
    # Warmup opcional del modelo de embeddings
    try:
        from ai_agent_service.infrastructure.embeddings import OnnxEmbeddingAdapter
        adapter = OnnxEmbeddingAdapter(model_name=settings.EMBEDDING_MODEL_NAME)
        await adapter.embed_text("warmup")
        logger.info("Embedding model warmed up.")
    except Exception as exc:
        logger.warning("Embedding warmup deferred: %s", exc)

    yield
    logger.info("Stopping %s...", settings.SERVICE_NAME)


app = FastAPI(
    title="Nexus AI Agent Service",
    version="1.0.0",
    description="Microservicio de Asistente Conversacional y RAG Gamer con Streaming SSE",
    lifespan=lifespan,
)

# Hardening común: errores fail-closed (A10), CORS/TrustedHost/cabeceras (A06), logs y OTel (A09).
configure_service(app, settings.SERVICE_NAME)

app.include_router(assistant_router, prefix="/api/v1")
