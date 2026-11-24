import json
import uuid
import redis.asyncio as redis
from cart_service.config import get_settings
from cart_service.domain.entities import Cart, CartItem
from cart_service.domain.ports import CartRepositoryPort


class RedisCartRepository(CartRepositoryPort):
    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client
        self._settings = get_settings()

    def _key(self, user_id: str) -> str:
        return f"cart:{user_id}"

    async def get_by_user_id(self, user_id: str) -> Cart:
        raw = await self._redis.get(self._key(user_id))
        if not raw:
            return Cart(user_id=user_id)

        data = json.loads(raw)
        items = [
            CartItem(
                product_id=uuid.UUID(item["product_id"]),
                title=item["title"],
                unit_price_clp=item["unit_price_clp"],
                quantity=item["quantity"],
                image_url=item.get("image_url"),
            )
            for item in data.get("items", [])
        ]
        return Cart(user_id=user_id, items=items)

    async def save(self, cart: Cart) -> Cart:
        payload = {
            "user_id": cart.user_id,
            "items": [
                {
                    "product_id": str(item.product_id),
                    "title": item.title,
                    "unit_price_clp": item.unit_price_clp,
                    "quantity": item.quantity,
                    "image_url": item.image_url,
                }
                for item in cart.items
            ],
        }
        await self._redis.set(
            self._key(cart.user_id),
            json.dumps(payload),
            ex=self._settings.CART_TTL_SECONDS,
        )
        return cart

    async def clear(self, user_id: str) -> None:
        await self._redis.delete(self._key(user_id))

