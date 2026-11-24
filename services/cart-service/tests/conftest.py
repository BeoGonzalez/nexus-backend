import copy
import uuid

import httpx
import pytest

from cart_service.domain.entities import Cart
from cart_service.domain.ports import CartRepositoryPort, CatalogClientPort

PRODUCT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CATALOG_ITEM = {"id": str(PRODUCT_ID), "title": "Hades II", "price_clp": 19990, "stock": 3, "image_url": None}


class InMemoryCartRepository(CartRepositoryPort):
    """Guarda copias profundas para comportarse como un almacén externo (Redis)."""

    def __init__(self) -> None:
        self.carts: dict[str, Cart] = {}

    async def get_by_user_id(self, user_id: str) -> Cart:
        return copy.deepcopy(self.carts.get(user_id, Cart(user_id=user_id)))

    async def save(self, cart: Cart) -> Cart:
        self.carts[cart.user_id] = copy.deepcopy(cart)
        return cart

    async def clear(self, user_id: str) -> None:
        self.carts.pop(user_id, None)


class FakeCatalogClient(CatalogClientPort):
    def __init__(self, products: dict[uuid.UUID, dict]) -> None:
        self.products = products

    async def get_product_details(self, product_id: uuid.UUID) -> dict | None:
        return self.products.get(product_id)


@pytest.fixture
def repo():
    return InMemoryCartRepository()


@pytest.fixture
def catalog():
    return FakeCatalogClient({PRODUCT_ID: dict(CATALOG_ITEM)})


@pytest.fixture
async def client(repo, catalog):
    from cart_service.application.services import CartService
    from cart_service.main import app
    from cart_service.presentation.router import get_cart_service

    app.dependency_overrides[get_cart_service] = lambda: CartService(repo, catalog)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cart") as c:
        yield c
    app.dependency_overrides.clear()
