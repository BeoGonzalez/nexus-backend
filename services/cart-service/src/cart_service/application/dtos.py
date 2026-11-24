import uuid
from pydantic import BaseModel, Field


class AddToCartRequest(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=100)


class UpdateCartItemRequest(BaseModel):
    quantity: int = Field(..., ge=0, le=100)


class CartItemResponse(BaseModel):
    product_id: uuid.UUID
    title: str
    unit_price_clp: int
    quantity: int
    subtotal_clp: int
    image_url: str | None = None


class CartResponse(BaseModel):
    user_id: str
    items: list[CartItemResponse]
    total_amount_clp: int
    total_items_count: int

