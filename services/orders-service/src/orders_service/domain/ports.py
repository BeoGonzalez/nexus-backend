from abc import ABC, abstractmethod
import uuid
from orders_service.domain.entities import Order, OrderStatus


class OrderRepositoryPort(ABC):
    @abstractmethod
    async def create(self, order: Order) -> Order:
        ...

    @abstractmethod
    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        ...

    @abstractmethod
    async def get_by_user_id(self, user_id: str) -> list[Order]:
        ...

    @abstractmethod
    async def update_status(self, order_id: uuid.UUID, status: OrderStatus) -> None:
        ...

    @abstractmethod
    async def mark_paid_and_emit_event(self, order_id: uuid.UUID, payment_id: str) -> Order | None:
        ...
