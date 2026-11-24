from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import uuid
from nexus_core.domain.entities import BaseEntity


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    STOCK_CONFIRMED = "STOCK_CONFIRMED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    DELIVERED = "DELIVERED"


# Estados desde los que una orden puede pagarse (máquina de estados; cualquier otro -> 409).
PAYABLE_STATUSES = (OrderStatus.PENDING, OrderStatus.STOCK_CONFIRMED)


@dataclass
class OrderItem:
    product_id: uuid.UUID
    quantity: int
    unit_price_clp: int
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    product_title: str | None = None

    @property
    def subtotal_clp(self) -> int:
        return self.unit_price_clp * self.quantity


@dataclass
class Order(BaseEntity):
    user_id: str = ""
    user_email: str | None = None
    status: OrderStatus = OrderStatus.PENDING
    items: list[OrderItem] = field(default_factory=list)
    total_amount_clp: int = 0
    idempotency_key: str | None = None

    def calculate_total(self) -> None:
        self.total_amount_clp = sum(item.subtotal_clp for item in self.items)
