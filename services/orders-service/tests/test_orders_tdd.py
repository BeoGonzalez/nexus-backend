import uuid
import pytest
from orders_service.domain.entities import Order, OrderItem, OrderStatus
from orders_service.domain.ports import OrderRepositoryPort


class InMemoryOrderRepository(OrderRepositoryPort):
    def __init__(self) -> None:
        self.orders: dict[uuid.UUID, Order] = {}
        self.emitted_outbox_events: list[dict] = []

    async def create(self, order: Order) -> Order:
        self.orders[order.id] = order
        self.emitted_outbox_events.append({
            "event_type": "order.created",
            "order_id": str(order.id),
            "user_id": order.user_id,
            "user_email": order.user_email,
            "total_amount_clp": order.total_amount_clp,
        })
        return order

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        return self.orders.get(order_id)

    async def get_by_user_id(self, user_id: str) -> list[Order]:
        return [o for o in self.orders.values() if o.user_id == user_id]

    async def update_status(self, order_id: uuid.UUID, status: OrderStatus) -> None:
        if order_id in self.orders:
            self.orders[order_id].status = status

    async def mark_paid_and_emit_event(self, order_id: uuid.UUID, payment_id: str) -> Order | None:
        order = self.orders.get(order_id)
        if not order:
            return None
        order.status = OrderStatus.PAID
        self.emitted_outbox_events.append({
            "event_type": "order.payment_succeeded",
            "order_id": str(order_id),
            "user_id": order.user_id,
            "user_email": order.user_email,
            "payment_id": payment_id,
            "amount_paid_clp": order.total_amount_clp,
        })
        return order


@pytest.mark.asyncio
async def test_order_creation_captures_buyer_email_and_outbox():
    repo = InMemoryOrderRepository()
    order_id = uuid.uuid4()
    prod_id = uuid.uuid4()

    order = Order(
        id=order_id,
        user_id="usr-cognito-987",
        user_email="buyer.gamer@gmail.com",
        items=[
            OrderItem(
                product_id=prod_id,
                product_title="Cyberpunk 2077",
                quantity=1,
                unit_price_clp=29990,
            )
        ],
        status=OrderStatus.PENDING,
    )
    order.calculate_total()
    created = await repo.create(order)

    assert created.user_email == "buyer.gamer@gmail.com"
    assert created.total_amount_clp == 29990
    assert len(repo.emitted_outbox_events) == 1
    assert repo.emitted_outbox_events[0]["user_email"] == "buyer.gamer@gmail.com"
    assert repo.emitted_outbox_events[0]["event_type"] == "order.created"


@pytest.mark.asyncio
async def test_order_payment_completion_emits_payment_succeeded_event():
    repo = InMemoryOrderRepository()
    order_id = uuid.uuid4()

    order = Order(
        id=order_id,
        user_id="usr-local-555",
        user_email="local.gamer@hotmail.com",
        items=[
            OrderItem(
                product_id=uuid.uuid4(),
                product_title="God of War Ragnarok",
                quantity=1,
                unit_price_clp=42990,
            )
        ],
        status=OrderStatus.PENDING,
    )
    order.calculate_total()
    await repo.create(order)

    # Procesar pago
    paid_order = await repo.mark_paid_and_emit_event(order_id, "pay-transbank-xyz789")
    assert paid_order is not None
    assert paid_order.status == OrderStatus.PAID

    payment_event = next(e for e in repo.emitted_outbox_events if e["event_type"] == "order.payment_succeeded")
    assert payment_event["user_email"] == "local.gamer@hotmail.com"
    assert payment_event["payment_id"] == "pay-transbank-xyz789"
    assert payment_event["amount_paid_clp"] == 42990

