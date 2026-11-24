from datetime import datetime
import uuid
from pydantic import BaseModel, Field
from orders_service.domain.entities import OrderStatus


class OrderItemRequest(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(..., gt=0, le=100)


class CreateOrderRequest(BaseModel):
    # Máximo 50 ítems: cada uno implica una consulta HTTP al catálogo (amplificación / DoS).
    items: list[OrderItemRequest] = Field(..., min_length=1, max_length=50)
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,64}$")


class OrderItemResponse(BaseModel):
    product_id: uuid.UUID
    quantity: int
    unit_price_clp: int
    subtotal_clp: int
    product_title: str | None = None


class OrderResponse(BaseModel):
    id: uuid.UUID
    user_id: str
    user_email: str | None = None
    status: OrderStatus
    items: list[OrderItemResponse]
    total_amount_clp: int
    created_at: datetime


class ProcessPaymentRequest(BaseModel):
    payment_id: str = Field(
        default_factory=lambda: f"pay-{uuid.uuid4().hex[:12]}", pattern=r"^[A-Za-z0-9._:-]{1,64}$"
    )
