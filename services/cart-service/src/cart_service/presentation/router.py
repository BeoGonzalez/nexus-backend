import uuid
from fastapi import APIRouter, Depends, status
import redis.asyncio as redis

from cart_service.application.dtos import (
    AddToCartRequest,
    CartItemResponse,
    CartResponse,
    UpdateCartItemRequest,
)
from cart_service.application.services import CartService
from cart_service.config import get_settings
from cart_service.domain.entities import Cart
from cart_service.infrastructure.catalog_client import HttpCatalogClient
from cart_service.infrastructure.redis_repository import RedisCartRepository
from nexus_security.dependencies import get_cart_owner

router = APIRouter(prefix="/api/v1/cart", tags=["Cart Service"])
settings = get_settings()

_redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)


def get_cart_service() -> CartService:
    repo = RedisCartRepository(_redis_client)
    catalog = HttpCatalogClient()
    return CartService(repo, catalog)


def _to_response(cart: Cart) -> CartResponse:
    return CartResponse(
        user_id=cart.user_id,
        items=[
            CartItemResponse(
                product_id=item.product_id,
                title=item.title,
                unit_price_clp=item.unit_price_clp,
                quantity=item.quantity,
                subtotal_clp=item.subtotal_clp,
                image_url=item.image_url,
            )
            for item in cart.items
        ],
        total_amount_clp=cart.total_amount_clp,
        total_items_count=cart.total_items_count,
    )


@router.get("", response_model=CartResponse)
async def get_cart(
    owner: str = Depends(get_cart_owner),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    cart = await service.get_cart(owner)
    return _to_response(cart)


@router.post("/items", response_model=CartResponse, status_code=status.HTTP_201_CREATED)
async def add_item(
    request: AddToCartRequest,
    owner: str = Depends(get_cart_owner),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    cart = await service.add_item(owner, request)
    return _to_response(cart)


@router.put("/items/{product_id}", response_model=CartResponse)
async def update_item(
    product_id: uuid.UUID,
    request: UpdateCartItemRequest,
    owner: str = Depends(get_cart_owner),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    cart = await service.update_item_quantity(owner, product_id, request.quantity)
    return _to_response(cart)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cart(
    owner: str = Depends(get_cart_owner),
    service: CartService = Depends(get_cart_service),
) -> None:
    await service.clear_cart(owner)


@router.get("/health")
async def health_check() -> dict:
    return {"status": "healthy", "service": "cart-service"}

