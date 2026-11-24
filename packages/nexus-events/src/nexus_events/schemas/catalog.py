from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field


class StockReservedEvent(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = "catalog.stock_reserved"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    order_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int


class StockReservationFailedEvent(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = "catalog.stock_reservation_failed"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    order_id: uuid.UUID
    product_id: uuid.UUID
    reason: str


class StockReleasedEvent(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = "catalog.stock_released"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    order_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int

