import asyncio
import json
import uuid

from sqlalchemy import select

from nexus_events.outbox import OutboxEventModel
from nexus_events.publisher import EventPublisher
from orders_service.domain.entities import Order, OrderItem
from orders_service.infrastructure.outbox_worker import OutboxWorker
from orders_service.infrastructure.repositories import PostgresOrderRepository


async def _wait_until(predicate, timeout=15.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.2)
    raise AssertionError("condición no alcanzada a tiempo")


async def test_worker_publishes_pending_events_to_sns_and_marks_them_processed(session_factory, aws_events):
    order_queue = aws_events.queue("orders", {"event_type": [{"prefix": "order."}]})
    order = Order(user_id="alice", user_email="alice@b.cl", items=[OrderItem(uuid.uuid4(), 1, 1000)])
    order.calculate_total()
    async with session_factory() as s:
        await PostgresOrderRepository(s).create(order)
    async with session_factory() as s:
        await PostgresOrderRepository(s).mark_paid_and_emit_event(order.id, "pay-1")

    task = asyncio.create_task(OutboxWorker(session_factory, EventPublisher(aws_events.topic_arn)).start())

    async def all_processed():
        async with session_factory() as s:
            rows = (await s.execute(select(OutboxEventModel))).scalars().all()
            return len(rows) == 2 and all(r.processed and r.processed_at for r in rows)

    try:
        await _wait_until(all_processed)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    msgs = aws_events.sqs.receive_message(
        QueueUrl=order_queue, MaxNumberOfMessages=10, MessageAttributeNames=["All"]
    )["Messages"]
    received = sorted(m["MessageAttributes"]["event_type"]["StringValue"] for m in msgs)
    assert received == ["order.created", "order.payment_succeeded"]
    assert all(json.loads(m["Body"])["order_id"] == str(order.id) for m in msgs)


async def test_failed_publish_leaves_event_pending(session_factory):
    class DownPublisher:
        async def publish_raw(self, event_type, payload_json):
            raise ConnectionError("SNS no disponible (simulado)")

    order = Order(user_id="bob", user_email="bob@b.cl", items=[OrderItem(uuid.uuid4(), 1, 1000)])
    order.calculate_total()
    async with session_factory() as s:
        await PostgresOrderRepository(s).create(order)

    task = asyncio.create_task(OutboxWorker(session_factory, DownPublisher()).start())
    await asyncio.sleep(1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    async with session_factory() as s:
        rows = (await s.execute(select(OutboxEventModel).where(OutboxEventModel.aggregate_id == str(order.id)))).scalars().all()
    assert rows and not any(r.processed for r in rows)
