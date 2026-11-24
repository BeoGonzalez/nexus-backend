import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI

from nexus_core.infrastructure.database import (
    Base,
    DatabaseConnectionConfig,
    create_db_engine,
    create_session_factory,
)
from nexus_core.infrastructure.logging import setup_service_logging
from nexus_core.presentation.security import configure_service
from nexus_events.publisher import EventPublisher
from orders_service.config import get_settings
from orders_service.infrastructure.outbox_worker import OutboxWorker
from orders_service.presentation.router import router as orders_router

settings = get_settings()
logger = setup_service_logging(settings.SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s on port %d...", settings.SERVICE_NAME, settings.PORT)
    engine = create_db_engine(DatabaseConnectionConfig(database_url=settings.DATABASE_URL))
    session_factory = create_session_factory(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    publisher = EventPublisher(settings.EVENTS_TOPIC_ARN, region=settings.AWS_REGION)
    worker = OutboxWorker(session_factory, publisher)
    worker_task = asyncio.create_task(worker.start())

    yield

    worker_task.cancel()
    await publisher.close()
    await engine.dispose()
    logger.info("Stopping %s...", settings.SERVICE_NAME)


app = FastAPI(
    title="Nexus Orders Service",
    version="1.0.0",
    description="Microservicio de Gestión de Órdenes y Pagos (Saga & Outbox)",
    lifespan=lifespan,
)

# Hardening común: errores fail-closed (A10), CORS/TrustedHost/cabeceras (A06), logs y OTel (A09).
configure_service(app, settings.SERVICE_NAME)

app.include_router(orders_router)
