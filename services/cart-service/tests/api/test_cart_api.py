import uuid

import pytest

from nexus_testkit import auth_headers

PRODUCT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")  # mismo id que conftest.CATALOG_ITEM

BASE = "/api/v1/cart"


async def test_app_imports_without_network():
    from cart_service.main import app

    assert BASE in app.openapi()["paths"]


@pytest.mark.parametrize("method,path", [("get", ""), ("post", "/items"), ("put", f"/items/{PRODUCT_ID}"), ("delete", "")])
async def test_all_cart_routes_require_authentication(client, method, path):
    kwargs = {"json": {"product_id": str(PRODUCT_ID), "quantity": 1}} if method in ("post", "put") else {}
    assert (await client.request(method.upper(), BASE + path, **kwargs)).status_code == 401


async def test_guest_cart_uses_x_guest_id(client):
    g = {"X-Guest-Id": str(uuid.uuid4())}
    r = await client.post(f"{BASE}/items", json={"product_id": str(PRODUCT_ID), "quantity": 1}, headers=g)
    assert r.status_code == 201
    body = (await client.get(BASE, headers=g)).json()
    assert body["user_id"] == f"guest:{g['X-Guest-Id']}"
    assert body["total_items_count"] == 1


async def test_x_user_id_header_cannot_read_another_users_cart(client):
    await client.post(f"{BASE}/items", json={"product_id": str(PRODUCT_ID), "quantity": 1}, headers=auth_headers(sub="alice"))
    assert (await client.get(BASE, headers={"X-User-Id": "alice"})).status_code == 401


async def test_add_item_then_read_cart(client):
    h = auth_headers(sub="u1")
    r = await client.post(f"{BASE}/items", json={"product_id": str(PRODUCT_ID), "quantity": 2}, headers=h)
    assert r.status_code == 201
    body = (await client.get(BASE, headers=h)).json()
    assert (body["user_id"], body["total_amount_clp"], body["total_items_count"]) == ("u1", 39980, 2)
    assert body["items"][0]["subtotal_clp"] == 39980


async def test_add_item_with_zero_quantity_is_422(client):
    r = await client.post(f"{BASE}/items", json={"product_id": str(PRODUCT_ID), "quantity": 0}, headers=auth_headers())
    assert r.status_code == 422


async def test_add_unknown_product_is_404(client):
    r = await client.post(f"{BASE}/items", json={"product_id": str(uuid.uuid4())}, headers=auth_headers())
    assert r.status_code == 404


async def test_add_beyond_stock_is_409(client):
    r = await client.post(f"{BASE}/items", json={"product_id": str(PRODUCT_ID), "quantity": 9}, headers=auth_headers())
    assert r.status_code == 409


async def test_update_quantity(client):
    h = auth_headers()
    await client.post(f"{BASE}/items", json={"product_id": str(PRODUCT_ID), "quantity": 1}, headers=h)
    r = await client.put(f"{BASE}/items/{PRODUCT_ID}", json={"quantity": 3}, headers=h)
    assert r.json()["total_items_count"] == 3


async def test_clear_cart_returns_204_and_empties(client):
    h = auth_headers()
    await client.post(f"{BASE}/items", json={"product_id": str(PRODUCT_ID), "quantity": 1}, headers=h)
    assert (await client.delete(BASE, headers=h)).status_code == 204
    assert (await client.get(BASE, headers=h)).json()["items"] == []


async def test_users_do_not_see_each_others_cart(client):
    await client.post(f"{BASE}/items", json={"product_id": str(PRODUCT_ID), "quantity": 1}, headers=auth_headers(sub="a"))
    assert (await client.get(BASE, headers=auth_headers(sub="b"))).json()["items"] == []
