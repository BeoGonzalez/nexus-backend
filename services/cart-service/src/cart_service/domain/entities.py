import uuid
from dataclasses import dataclass, field


@dataclass
class CartItem:
    product_id: uuid.UUID
    title: str
    unit_price_clp: int
    quantity: int
    image_url: str | None = None

    @property
    def subtotal_clp(self) -> int:
        return self.unit_price_clp * self.quantity


@dataclass
class Cart:
    user_id: str
    items: list[CartItem] = field(default_factory=list)

    @property
    def total_amount_clp(self) -> int:
        return sum(item.subtotal_clp for item in self.items)

    @property
    def total_items_count(self) -> int:
        return sum(item.quantity for item in self.items)

