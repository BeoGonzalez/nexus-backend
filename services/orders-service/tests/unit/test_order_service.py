import uuid

import httpx
import pytest
import respx

from nexus_core.domain.exceptions import BusinessRuleViolationException, ResourceNotFoundException
from orders_service.application.dtos import CreateOrderRequest, OrderItemRequest
from orders_service.application.services import OrderService
from orders_service.domain.entities import OrderStatus

CATALOG = "http://catalog.test/api/v1/catalog/products"
P1, P2 = uuid.uuid4(), uuid.uuid4()


def _request(*lines) -> CreateOrderRequest:
    return CreateOrderRequest(items=[OrderItemRequest(product_id=p, quantity=q) for p, q in lines])


@respx.mock
async def test_order_uses_catalog_prices_and_totals(repo):
    respx.get(f"{CATALOG}/{P1}").respond(200, json={"title": "Hades II", "price_clp": 19990, "stock": 10})
    respx.get(f"{CATALOG}/{P2}").respond(200, json={"title": "Celeste", "price_clp": 5000, "stock": 1})
    order = await OrderService(repo).create_order("u1", _request((P1, 2), (P2, 1)), user_email="a@b.cl")
    assert order.total_amount_clp == 44980
    assert order.status == OrderStatus.PENDING
    assert [(i.product_title, i.unit_price_clp) for i in order.items] == [("Hades II", 19990), ("Celeste", 5000)]
    assert (order.user_id, order.user_email) == ("u1", "a@b.cl")
    assert repo.outbox == ["order.created"]


@respx.mock
async def test_insufficient_stock_rejects_order_and_persists_nothing(repo):
    respx.get(f"{CATALOG}/{P1}").respond(200, json={"title": "Hades II", "price_clp": 19990, "stock": 1})
    with pytest.raises(BusinessRuleViolationException, match="Stock insuficiente"):
        await OrderService(repo).create_order("u1", _request((P1, 2)))
    assert repo.orders == {}


@respx.mock
async def test_product_missing_in_catalog_is_not_found(repo):
    respx.get(f"{CATALOG}/{P1}").respond(404)
    with pytest.raises(ResourceNotFoundException):
        await OrderService(repo).create_order("u1", _request((P1, 1)))


@respx.mock
async def test_catalog_unreachable_is_business_rule_violation(repo):
    respx.get(f"{CATALOG}/{P1}").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(BusinessRuleViolationException, match="no disponible"):
        await OrderService(repo).create_order("u1", _request((P1, 1)))


async def test_paying_unknown_order_is_not_found(repo):
    with pytest.raises(ResourceNotFoundException):
        await OrderService(repo).complete_payment(uuid.uuid4(), "pay-1")


async def test_get_unknown_order_is_not_found(repo):
    with pytest.raises(ResourceNotFoundException):
        await OrderService(repo).get_order_by_id(uuid.uuid4())
