from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI

from cart_service.config import get_settings
from cart_service.presentation.router import router as cart_router
from nexus_core.infrastructure.logging import setup_service_logging
from nexus_core.presentation.security import configure_service

settings = get_settings()
logger = setup_service_logging(settings.SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s on port %d...", settings.SERVICE_NAME, settings.PORT)
    yield
    logger.info("Stopping %s...", settings.SERVICE_NAME)


app = FastAPI(
    title="Nexus Cart Service",
    version="1.0.0",
    description="Microservicio de Carrito de Compras de Alta Velocidad (Redis)",
    lifespan=lifespan,
)

# Hardening común: errores fail-closed (A10), CORS/TrustedHost/cabeceras (A06), logs y OTel (A09).
configure_service(app, settings.SERVICE_NAME)

app.include_router(cart_router)
