import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nexus_events.outbox import OutboxEventModel
from nexus_events.schemas.orders import OrderCreatedEvent, PaymentSucceededEvent
from orders_service.domain.entities import Order, OrderItem, OrderStatus
from orders_service.infrastructure.models import OrderItemModel, OrderModel
from orders_service.infrastructure.repositories import PostgresOrderRepository


def _order(user="alice", key=None) -> Order:
    order = Order(user_id=user, user_email=f"{user}@b.cl", idempotency_key=key,
                  items=[OrderItem(uuid.uuid4(), 2, 19990, product_title="Hades II")])
    order.calculate_total()
    return order


async def _outbox(session_factory) -> list[OutboxEventModel]:
    async with session_factory() as s:
        return list((await s.execute(select(OutboxEventModel).order_by(OutboxEventModel.created_at))).scalars())


async def test_create_persists_order_items_and_outbox_event_atomically(session_factory):
    async with session_factory() as s:
        created = await PostgresOrderRepository(s).create(_order())
    async with session_factory() as s:
        found = await PostgresOrderRepository(s).get_by_id(created.id)
    assert (found.user_id, found.total_amount_clp, found.status) == ("alice", 39980, OrderStatus.PENDING)
    assert [(i.quantity, i.unit_price_clp) for i in found.items] == [(2, 19990)]
    [event] = await _outbox(session_factory)
    assert (event.event_type, event.aggregate_id, event.processed) == ("order.created", str(created.id), False)


async def test_order_created_outbox_payload_matches_shared_event_contract(session_factory):
    async with session_factory() as s:
        created = await PostgresOrderRepository(s).create(_order())
    [event] = await _outbox(session_factory)
    parsed = OrderCreatedEvent.model_validate(json.loads(event.payload_json))
    assert (parsed.order_id, parsed.user_email, parsed.total_amount_clp) == (created.id, "alice@b.cl", 39980)


async def test_mark_paid_updates_status_and_emits_payment_event(session_factory):
    async with session_factory() as s:
        created = await PostgresOrderRepository(s).create(_order())
    async with session_factory() as s:
        paid = await PostgresOrderRepository(s).mark_paid_and_emit_event(created.id, "pay-1")
    assert paid.status == OrderStatus.PAID
    async with session_factory() as s:
        assert (await PostgresOrderRepository(s).get_by_id(created.id)).status == OrderStatus.PAID
    events = await _outbox(session_factory)
    assert [e.event_type for e in events] == ["order.created", "order.payment_succeeded"]
    payment = PaymentSucceededEvent.model_validate(json.loads(events[1].payload_json))
    assert (payment.payment_id, payment.amount_paid_clp, payment.user_email) == ("pay-1", 39980, "alice@b.cl")


async def test_mark_paid_unknown_order_returns_none_and_emits_nothing(session_factory):
    async with session_factory() as s:
        assert await PostgresOrderRepository(s).mark_paid_and_emit_event(uuid.uuid4(), "pay-x") is None
    assert await _outbox(session_factory) == []


async def test_orders_by_user_are_isolated_and_newest_first(session_factory):
    async with session_factory() as s:
        repo = PostgresOrderRepository(s)
        first = await repo.create(_order("alice"))
        second = await repo.create(_order("alice"))
        await repo.create(_order("bob"))
    async with session_factory() as s:
        ids = [o.id for o in await PostgresOrderRepository(s).get_by_user_id("alice")]
    assert ids == [second.id, first.id]


async def test_item_with_zero_quantity_violates_constraint(session_factory):
    async with session_factory() as s:
        order = OrderModel(user_id="u", total_amount_clp=0, status=OrderStatus.PENDING)
        order.items = [OrderItemModel(product_id=uuid.uuid4(), quantity=0, unit_price_clp=100)]
        s.add(order)
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_duplicate_idempotency_key_is_handled(session_factory):
    from nexus_core.domain.exceptions import BusinessRuleViolationException

    async with session_factory() as s:
        first = await PostgresOrderRepository(s).create(_order(key="checkout-123"))
    async with session_factory() as s:
        try:
            second = await PostgresOrderRepository(s).create(_order(key="checkout-123"))
        except BusinessRuleViolationException:
            return
        assert second.id == first.id


async def test_paying_twice_emits_single_payment_event(session_factory):
    async with session_factory() as s:
        created = await PostgresOrderRepository(s).create(_order())
    for pay_id in ("pay-1", "pay-2"):
        async with session_factory() as s:
            try:
                await PostgresOrderRepository(s).mark_paid_and_emit_event(created.id, pay_id)
            except Exception:
                pass
    events = [e.event_type for e in await _outbox(session_factory)]
    assert events.count("order.payment_succeeded") == 1


async def test_concurrent_payments_emit_single_payment_event(session_factory):
    """Carrera: dos pagos simultáneos de la misma orden (UPDATE condicional atómico en Postgres)."""
    import asyncio

    from nexus_core.domain.exceptions import BusinessRuleViolationException

    async with session_factory() as s:
        created = await PostgresOrderRepository(s).create(_order())

    async def pay(pay_id: str):
        async with session_factory() as s:
            return await PostgresOrderRepository(s).mark_paid_and_emit_event(created.id, pay_id)

    results = await asyncio.gather(*(pay(f"pay-{i}") for i in range(5)), return_exceptions=True)
    assert sum(1 for r in results if isinstance(r, BusinessRuleViolationException)) == 4
    events = [e.event_type for e in await _outbox(session_factory)]
    assert events.count("order.payment_succeeded") == 1


async def test_idempotency_key_of_another_user_never_returns_their_order(session_factory):
    """IDOR: adivinar la clave de idempotencia de otro comprador no debe exponer su orden."""
    from nexus_core.domain.exceptions import BusinessRuleViolationException

    async with session_factory() as s:
        await PostgresOrderRepository(s).create(_order(user="alice", key="checkout-777"))
    async with session_factory() as s:
        with pytest.raises(BusinessRuleViolationException):
            await PostgresOrderRepository(s).create(_order(user="mallory", key="checkout-777"))


async def test_same_user_retry_with_same_key_returns_same_order(session_factory):
    async with session_factory() as s:
        first = await PostgresOrderRepository(s).create(_order(user="alice", key="checkout-888"))
    async with session_factory() as s:
        second = await PostgresOrderRepository(s).create(_order(user="alice", key="checkout-888"))
    assert second.id == first.id
