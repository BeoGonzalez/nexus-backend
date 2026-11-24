"""Pruebas de ataque contra la lógica de negocio de órdenes (A01, A04/A06 Insecure Design)."""

import uuid

import pytest
import respx

from nexus_testkit import auth_headers

BASE = "/api/v1/orders"
CATALOG = "http://catalog.test/api/v1/catalog/products"
PID = uuid.uuid4()


@pytest.fixture
def catalog_ok():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(url__regex=rf"{CATALOG}/.*").respond(200, json={"title": "Hades II", "price_clp": 19990, "stock": 5})
        yield route


async def _create(client, sub="alice", **extra):
    body = {"items": [{"product_id": str(PID), "quantity": 1}], **extra}
    return await client.post(BASE, json=body, headers=auth_headers(sub=sub, email=f"{sub}@b.cl"))


async def test_paying_an_already_paid_order_is_rejected_and_emits_no_second_event(client, catalog_ok, repo):
    oid = (await _create(client)).json()["id"]
    assert (await client.post(f"{BASE}/{oid}/pay", headers=auth_headers(sub="alice"))).status_code == 200
    r = await client.post(f"{BASE}/{oid}/pay", headers=auth_headers(sub="alice"))
    assert r.status_code == 409
    assert repo.outbox.count("order.payment_succeeded") == 1


async def test_cancelled_order_cannot_be_paid(client, catalog_ok, repo):
    from orders_service.domain.entities import OrderStatus

    oid = (await _create(client)).json()["id"]
    repo.orders[uuid.UUID(oid)].status = OrderStatus.CANCELLED
    assert (await client.post(f"{BASE}/{oid}/pay", headers=auth_headers(sub="alice"))).status_code == 409


async def test_order_with_hundreds_of_items_is_rejected_before_calling_catalog(client, catalog_ok):
    """Amplificación: cada ítem es una petición HTTP al catálogo."""
    items = [{"product_id": str(uuid.uuid4()), "quantity": 1} for _ in range(51)]
    r = await client.post(BASE, json={"items": items}, headers=auth_headers())
    assert r.status_code == 422
    assert catalog_ok.call_count == 0


async def test_absurd_quantity_is_rejected(client, catalog_ok):
    r = await client.post(BASE, json={"items": [{"product_id": str(PID), "quantity": 10**9}]}, headers=auth_headers())
    assert r.status_code == 422


@pytest.mark.parametrize("key", ["k" * 65, "clave con espacios", "<script>"])
async def test_malformed_idempotency_key_is_rejected(client, catalog_ok, key):
    assert (await _create(client, idempotency_key=key)).status_code == 422


async def test_payment_id_cannot_inject_arbitrary_content(client, catalog_ok):
    oid = (await _create(client)).json()["id"]
    r = await client.post(f"{BASE}/{oid}/pay", json={"payment_id": "x" * 500}, headers=auth_headers(sub="alice"))
    assert r.status_code == 422
