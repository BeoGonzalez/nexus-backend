from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field


class OrderItemSchema(BaseModel):
    product_id: uuid.UUID
    quantity: int
    unit_price_clp: int
    product_title: str | None = None


class OrderCreatedEvent(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = "order.created"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    order_id: uuid.UUID
    user_id: str
    user_email: str | None = None
    items: list[OrderItemSchema]
    total_amount_clp: int


class PaymentSucceededEvent(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = "order.payment_succeeded"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    order_id: uuid.UUID
    user_id: str
    user_email: str | None = None
    payment_id: str
    amount_paid_clp: int


class PaymentFailedEvent(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = "order.payment_failed"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    order_id: uuid.UUID
    user_id: str
    user_email: str | None = None
    reason: str
