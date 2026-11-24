import uuid

import httpx
import pytest

from orders_service.domain.entities import Order, OrderStatus
from orders_service.domain.ports import OrderRepositoryPort

CATALOG = "http://catalog.test/api/v1/catalog/products"


class InMemoryOrderRepository(OrderRepositoryPort):
    def __init__(self) -> None:
        self.orders: dict[uuid.UUID, Order] = {}
        self.outbox: list[str] = []

    async def create(self, order: Order) -> Order:
        self.orders[order.id] = order
        self.outbox.append("order.created")
        return order

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        return self.orders.get(order_id)

    async def get_by_user_id(self, user_id: str) -> list[Order]:
        return [o for o in self.orders.values() if o.user_id == user_id]

    async def update_status(self, order_id: uuid.UUID, status: OrderStatus) -> None:
        self.orders[order_id].status = status

    async def mark_paid_and_emit_event(self, order_id: uuid.UUID, payment_id: str) -> Order | None:
        order = self.orders.get(order_id)
        if order:
            order.status = OrderStatus.PAID
            self.outbox.append("order.payment_succeeded")
        return order


@pytest.fixture
def repo():
    return InMemoryOrderRepository()


@pytest.fixture
async def client(repo):
    from orders_service.application.services import OrderService
    from orders_service.main import app
    from orders_service.presentation.router import get_order_service

    app.dependency_overrides[get_order_service] = lambda: OrderService(repo)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://orders") as c:
        yield c
    app.dependency_overrides.clear()
