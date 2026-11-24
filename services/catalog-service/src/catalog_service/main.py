from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI

from catalog_service.config import get_settings
from catalog_service.presentation.router import router as catalog_router
from nexus_core.infrastructure.database import (
    Base,
    DatabaseConnectionConfig,
    create_db_engine,
)
from nexus_core.infrastructure.logging import setup_service_logging
from nexus_core.presentation.security import configure_service

settings = get_settings()
logger = setup_service_logging(settings.SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s on port %d...", settings.SERVICE_NAME, settings.PORT)
    # Crear tablas si no existen
    engine = create_db_engine(DatabaseConnectionConfig(database_url=settings.DATABASE_URL))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()
    logger.info("Stopping %s...", settings.SERVICE_NAME)


app = FastAPI(
    title="Nexus Catalog Service",
    version="1.0.0",
    description="Microservicio de Catálogo de Productos e Inventario",
    lifespan=lifespan,
)

# Hardening común: errores fail-closed (A10), CORS/TrustedHost/cabeceras (A06), logs y OTel (A09).
configure_service(app, settings.SERVICE_NAME)

app.include_router(catalog_router)
