import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from fastapi import FastAPI

from nexus_core.infrastructure.logging import setup_service_logging
from nexus_core.presentation.security import configure_service
from notifications_service.application.handlers import NotificationEventHandler
from notifications_service.config import get_settings
from notifications_service.infrastructure.email_adapter import SmtpEmailAdapter
from notifications_service.infrastructure.sqs_consumer import build_notifications_consumer
from notifications_service.presentation.router import router as notifications_router

settings = get_settings()
logger = setup_service_logging(settings.SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s on port %d...", settings.SERVICE_NAME, settings.PORT)
    email_sender = SmtpEmailAdapter()
    handler = NotificationEventHandler(email_sender)
    consumer = build_notifications_consumer(handler)

    consumer_task = asyncio.create_task(consumer.start())
    yield
    consumer_task.cancel()
    logger.info("Stopping %s...", settings.SERVICE_NAME)


app = FastAPI(
    title="Nexus Notifications Service",
    version="1.0.0",
    description="Microservicio de Notificaciones Orientado a Eventos",
    lifespan=lifespan,
)

# Hardening común: errores fail-closed (A10), CORS/TrustedHost/cabeceras (A06), logs y OTel (A09).
configure_service(app, settings.SERVICE_NAME)

app.include_router(notifications_router)
