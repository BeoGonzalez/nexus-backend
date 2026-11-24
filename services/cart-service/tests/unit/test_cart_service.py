import uuid

import pytest

from cart_service.application.dtos import AddToCartRequest
from cart_service.application.services import CartService
from nexus_core.domain.exceptions import BusinessRuleViolationException, ResourceNotFoundException

PRODUCT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")  # mismo id que conftest.CATALOG_ITEM


@pytest.fixture
def service(repo, catalog):
    return CartService(repo, catalog)


async def test_add_item_uses_catalog_price_and_title(service, repo):
    cart = await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=2))
    [item] = cart.items
    assert (item.title, item.unit_price_clp, item.quantity) == ("Hades II", 19990, 2)
    assert repo.carts["u1"].total_amount_clp == 39980


async def test_add_unknown_product_is_not_found(service):
    with pytest.raises(ResourceNotFoundException):
        await service.add_item("u1", AddToCartRequest(product_id=uuid.uuid4()))


async def test_add_more_than_stock_is_rejected(service, repo):
    with pytest.raises(BusinessRuleViolationException):
        await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=4))
    assert "u1" not in repo.carts


async def test_adding_same_product_twice_merges_quantities(service):
    await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=1))
    cart = await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=1))
    assert [(i.product_id, i.quantity) for i in cart.items] == [(PRODUCT_ID, 2)]


async def test_carts_are_isolated_per_user(service):
    await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=1))
    assert (await service.get_cart("u2")).items == []


async def test_update_to_zero_removes_item(service):
    await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=2))
    assert (await service.update_item_quantity("u1", PRODUCT_ID, 0)).items == []


async def test_update_item_not_in_cart_is_not_found(service):
    with pytest.raises(ResourceNotFoundException):
        await service.update_item_quantity("u1", PRODUCT_ID, 1)


async def test_clear_cart_empties_it(service):
    await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=1))
    await service.clear_cart("u1")
    assert (await service.get_cart("u1")).items == []


async def test_add_existing_item_respects_stock(service):
    await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=2))
    with pytest.raises(BusinessRuleViolationException):
        await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=2))


async def test_update_quantity_respects_stock(service):
    await service.add_item("u1", AddToCartRequest(product_id=PRODUCT_ID, quantity=1))
    with pytest.raises(BusinessRuleViolationException):
        await service.update_item_quantity("u1", PRODUCT_ID, 50)


async def test_cart_line_limit_prevents_unbounded_carts(service, catalog, monkeypatch):
    from cart_service.application import services as svc

    monkeypatch.setattr(svc, "MAX_CART_LINES", 2)
    ids = [uuid.uuid4() for _ in range(3)]
    for pid in ids:
        catalog.products[pid] = {"title": "Juego", "price_clp": 1000, "stock": 10}
    for pid in ids[:2]:
        await service.add_item("u1", AddToCartRequest(product_id=pid, quantity=1))
    with pytest.raises(BusinessRuleViolationException):
        await service.add_item("u1", AddToCartRequest(product_id=ids[2], quantity=1))
