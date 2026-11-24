"""notifications-service consume su cola SQS (suscrita al topic SNS con el mismo filtro que Terraform)."""

import asyncio

from nexus_events.consumer import SqsEventConsumer
from nexus_events.publisher import EventPublisher
from notifications_service.application.handlers import NotificationEventHandler
from notifications_service.infrastructure.sqs_consumer import build_notifications_consumer, dispatch_to

NOTIFICATIONS_FILTER = {"event_type": [{"prefix": "order."}, "user.registered"]}  # = messaging.tf


async def test_each_event_reaches_its_notification_and_unrelated_ones_are_filtered(aws_events, sender):
    url = aws_events.queue("notifications", NOTIFICATIONS_FILTER)
    publisher = EventPublisher(aws_events.topic_arn)
    await publisher.publish_raw("order.created", '{"order_id": "o-1", "user_email": "a@b.cl", "total_amount_clp": 1}')
    await publisher.publish_raw("order.payment_succeeded", '{"order_id": "o-1", "user_email": "a@b.cl", "amount_paid_clp": 1}')
    await publisher.publish_raw("user.registered", '{"email": "new@b.cl", "full_name": "New"}')
    await publisher.publish_raw("catalog.stock_reserved", '{"order_id": "o-1"}')  # filtrado por SNS

    consumer = SqsEventConsumer(url, dispatch_to(NotificationEventHandler(sender)), wait_seconds=0)
    for _ in range(3):
        await consumer.poll_once()

    assert sorted(to for to, _, _ in sender.sent) == ["a@b.cl", "a@b.cl", "new@b.cl"]
    assert any("Boleta" in s for _, s, _ in sender.sent)
    assert any("Bienvenido" in s for _, s, _ in sender.sent)


async def test_unknown_event_type_is_acknowledged_without_sending(sender):
    await dispatch_to(NotificationEventHandler(sender))("order.shipped", {"order_id": "o-1"})
    assert sender.sent == []


def test_builder_uses_settings_queue_url(monkeypatch):
    from notifications_service import config

    monkeypatch.setenv("EVENTS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/1/q")
    config.get_settings.cache_clear()
    try:
        consumer = build_notifications_consumer(NotificationEventHandler(None))
        assert consumer._queue_url == "https://sqs.us-east-1.amazonaws.com/1/q"
    finally:
        config.get_settings.cache_clear()


async def test_without_queue_url_the_service_still_starts(monkeypatch):
    from notifications_service import config

    monkeypatch.setenv("EVENTS_QUEUE_URL", "")
    config.get_settings.cache_clear()
    try:
        await asyncio.wait_for(build_notifications_consumer(NotificationEventHandler(None)).start(), 1)
    finally:
        config.get_settings.cache_clear()
