"""Consumo de eventos de notificaciones desde SQS (cola suscrita al topic SNS de eventos).

La cola solo recibe order.* y user.registered (filtro de la suscripcion en Terraform); cualquier otro
tipo se confirma sin enviar nada.
"""

import logging

from nexus_events.consumer import EventHandler, SqsEventConsumer
from notifications_service.application.handlers import NotificationEventHandler
from notifications_service.config import get_settings

logger = logging.getLogger("notifications.consumer")


def dispatch_to(handler: NotificationEventHandler) -> EventHandler:
    routes = {
        "order.created": handler.handle_order_created,
        "order.payment_succeeded": handler.handle_payment_succeeded,
        "user.registered": handler.handle_user_registered,
    }

    async def dispatch(event_type: str, payload: dict) -> None:
        route = routes.get(event_type)
        if route is None:
            logger.info("Evento %s sin notificacion asociada: se ignora", event_type)
            return
        await route(payload)

    return dispatch


def build_notifications_consumer(handler: NotificationEventHandler) -> SqsEventConsumer:
    settings = get_settings()
    return SqsEventConsumer(settings.EVENTS_QUEUE_URL, dispatch_to(handler), region=settings.AWS_REGION)
