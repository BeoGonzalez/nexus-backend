import uuid
import pytest
from cart_service.application.dtos import AddToCartRequest
from cart_service.application.services import CartService
from cart_service.domain.entities import Cart
from cart_service.domain.ports import CartRepositoryPort, CatalogClientPort
from nexus_core.domain.exceptions import BusinessRuleViolationException


class InMemoryCartRepository(CartRepositoryPort):
    def __init__(self) -> None:
        self.carts: dict[str, Cart] = {}

    async def get_by_user_id(self, user_id: str) -> Cart:
        return self.carts.get(user_id, Cart(user_id=user_id))

    async def save(self, cart: Cart) -> Cart:
        self.carts[cart.user_id] = cart
        return cart

    async def clear(self, user_id: str) -> None:
        self.carts.pop(user_id, None)


class MockCatalogClient(CatalogClientPort):
    def __init__(self, catalog_data: dict) -> None:
        self.data = catalog_data

    async def get_product_details(self, product_id: uuid.UUID) -> dict | None:
        return self.data.get(product_id)


@pytest.mark.asyncio
async def test_cart_add_item_calculates_total():
    game_id = uuid.uuid4()
    catalog_client = MockCatalogClient({
        game_id: {
            "title": "Elden Ring",
            "price_clp": 35000,
            "stock": 5,
        }
    })
    repo = InMemoryCartRepository()
    service = CartService(repo, catalog_client)

    cart = await service.add_item("user-123", AddToCartRequest(product_id=game_id, quantity=2))
    assert len(cart.items) == 1
    assert cart.items[0].quantity == 2
    assert cart.items[0].subtotal_clp == 70000
    assert cart.total_amount_clp == 70000


@pytest.mark.asyncio
async def test_cart_rejects_quantity_exceeding_stock():
    game_id = uuid.uuid4()
    catalog_client = MockCatalogClient({
        game_id: {
            "title": "Limited Collector Item",
            "price_clp": 50000,
            "stock": 1,
        }
    })
    repo = InMemoryCartRepository()
    service = CartService(repo, catalog_client)

    with pytest.raises(BusinessRuleViolationException):
        await service.add_item("user-123", AddToCartRequest(product_id=game_id, quantity=3))

