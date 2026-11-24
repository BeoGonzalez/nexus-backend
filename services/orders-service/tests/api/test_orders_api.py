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
        mock.get(f"{CATALOG}/{PID}").respond(200, json={"title": "Hades II", "price_clp": 19990, "stock": 5})
        yield mock


async def _create(client, sub="alice", email="alice@b.cl", qty=1):
    return await client.post(BASE, json={"items": [{"product_id": str(PID), "quantity": qty}]},
                             headers=auth_headers(sub=sub, email=email))


async def test_app_imports_without_network():
    from orders_service.main import app

    assert BASE in app.openapi()["paths"]


async def test_create_order_binds_it_to_authenticated_buyer(client, catalog_ok):
    r = await _create(client)
    assert r.status_code == 201
    body = r.json()
    assert (body["user_id"], body["user_email"], body["status"], body["total_amount_clp"]) == (
        "alice", "alice@b.cl", "PENDING", 19990)
    assert body["items"][0]["subtotal_clp"] == 19990


async def test_create_order_without_token_is_401(client):
    r = await client.post(BASE, json={"items": [{"product_id": str(PID), "quantity": 1}]})
    assert r.status_code == 401


@pytest.mark.parametrize("payload", [{"items": []}, {"items": [{"product_id": str(PID), "quantity": 0}]}])
async def test_create_order_validation(client, payload):
    assert (await client.post(BASE, json=payload, headers=auth_headers())).status_code == 422


async def test_insufficient_stock_is_409(client, catalog_ok):
    assert (await _create(client, qty=9)).status_code == 409


async def test_list_returns_only_my_orders(client, catalog_ok):
    await _create(client, sub="alice")
    await _create(client, sub="bob")
    r = await client.get(BASE, headers=auth_headers(sub="alice"))
    assert [o["user_id"] for o in r.json()] == ["alice"]


async def test_get_unknown_order_is_404(client):
    assert (await client.get(f"{BASE}/{uuid.uuid4()}", headers=auth_headers())).status_code == 404


async def test_owner_can_pay_order(client, catalog_ok, repo):
    oid = (await _create(client)).json()["id"]
    r = await client.post(f"{BASE}/{oid}/pay", json={"payment_id": "pay-123"}, headers=auth_headers(sub="alice"))
    assert r.status_code == 200
    assert r.json()["status"] == "PAID"
    assert repo.outbox == ["order.created", "order.payment_succeeded"]


async def test_get_order_requires_auth(client, catalog_ok):
    oid = (await _create(client)).json()["id"]
    assert (await client.get(f"{BASE}/{oid}")).status_code == 401


async def test_get_other_users_order_is_forbidden(client, catalog_ok):
    oid = (await _create(client, sub="alice")).json()["id"]
    assert (await client.get(f"{BASE}/{oid}", headers=auth_headers(sub="mallory"))).status_code in (403, 404)


async def test_pay_requires_auth(client, catalog_ok):
    oid = (await _create(client)).json()["id"]
    assert (await client.post(f"{BASE}/{oid}/pay")).status_code == 401


async def test_pay_other_users_order_is_forbidden(client, catalog_ok):
    oid = (await _create(client, sub="alice")).json()["id"]
    r = await client.post(f"{BASE}/{oid}/pay", headers=auth_headers(sub="mallory"))
    assert r.status_code in (403, 404)


async def test_health(client):
    assert (await client.get(f"{BASE}/health")).json()["status"] == "healthy"
