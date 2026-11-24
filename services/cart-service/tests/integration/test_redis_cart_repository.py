import uuid

import pytest
import redis.asyncio as redis

from cart_service.config import get_settings
from cart_service.domain.entities import Cart, CartItem
from cart_service.infrastructure.redis_repository import RedisCartRepository


@pytest.fixture
async def redis_client(redis_url):
    client = redis.from_url(redis_url, decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


async def test_cart_roundtrip_preserves_items(redis_client):
    repo = RedisCartRepository(redis_client)
    pid = uuid.uuid4()
    await repo.save(Cart(user_id="u1", items=[
        CartItem(product_id=pid, title="Hades II", unit_price_clp=19990, quantity=2, image_url="http://img/x.png")
    ]))
    cart = await repo.get_by_user_id("u1")
    [item] = cart.items
    assert (item.product_id, item.title, item.unit_price_clp, item.quantity, item.image_url) == (
        pid, "Hades II", 19990, 2, "http://img/x.png")


async def test_saved_cart_expires_after_configured_ttl(redis_client):
    await RedisCartRepository(redis_client).save(Cart(user_id="u1"))
    ttl = await redis_client.ttl("cart:u1")
    assert get_settings().CART_TTL_SECONDS - 5 <= ttl <= get_settings().CART_TTL_SECONDS


async def test_clear_deletes_key(redis_client):
    repo = RedisCartRepository(redis_client)
    await repo.save(Cart(user_id="u1"))
    await repo.clear("u1")
    assert await redis_client.exists("cart:u1") == 0


async def test_unknown_user_gets_empty_cart(redis_client):
    cart = await RedisCartRepository(redis_client).get_by_user_id("nobody")
    assert (cart.user_id, cart.items) == ("nobody", [])
