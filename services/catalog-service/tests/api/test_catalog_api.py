import uuid

import pytest

from nexus_testkit import auth_headers

BASE = "/api/v1/catalog"
NEW_PRODUCT = {"title": "Celeste", "description": "Plataformas", "price_clp": 9990, "stock": 3}


async def test_app_imports_without_network():
    from catalog_service.main import app

    assert f"{BASE}/products" in app.openapi()["paths"]


async def test_list_products_returns_catalog(client):
    r = await client.get(f"{BASE}/products")
    assert r.status_code == 200
    assert [p["title"] for p in r.json()] == ["Hades II"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"skip": -1}])
async def test_list_rejects_out_of_range_pagination(client, params):
    assert (await client.get(f"{BASE}/products", params=params)).status_code == 422


async def test_get_product_by_id(client, repo):
    pid = next(iter(repo.products))
    r = await client.get(f"{BASE}/products/{pid}")
    assert r.status_code == 200
    assert r.json()["price_clp"] == 19990


async def test_get_unknown_product_is_404(client):
    assert (await client.get(f"{BASE}/products/{uuid.uuid4()}")).status_code == 404


async def test_admin_can_create_product(client, repo):
    r = await client.post(f"{BASE}/products", json=NEW_PRODUCT, headers=auth_headers(role="admin"))
    assert r.status_code == 201
    assert len(repo.products) == 2


async def test_customer_cannot_create_product(client, repo):
    r = await client.post(f"{BASE}/products", json=NEW_PRODUCT, headers=auth_headers(role="customer"))
    assert r.status_code == 403
    assert len(repo.products) == 1


async def test_anonymous_cannot_create_product(client):
    assert (await client.post(f"{BASE}/products", json=NEW_PRODUCT)).status_code == 401


@pytest.mark.parametrize("override", [{"price_clp": 0}, {"stock": -1}, {"title": "x"}])
async def test_create_rejects_invalid_product(client, override):
    r = await client.post(f"{BASE}/products", json={**NEW_PRODUCT, **override}, headers=auth_headers(role="admin"))
    assert r.status_code == 422


async def test_stock_patch_reserves_and_reports(client, repo):
    pid = next(iter(repo.products))
    r = await client.patch(f"{BASE}/products/{pid}/stock", json={"delta": -2}, headers=auth_headers(role="admin"))
    assert r.json() == {"product_id": str(pid), "updated": True}
    assert repo.products[pid].stock == 3


async def test_stock_patch_requires_authentication(client, repo):
    pid = next(iter(repo.products))
    r = await client.patch(f"{BASE}/products/{pid}/stock", json={"delta": -5})
    assert r.status_code == 401
    assert repo.products[pid].stock == 5


async def test_stock_patch_forbidden_for_customers(client, repo):
    pid = next(iter(repo.products))
    r = await client.patch(f"{BASE}/products/{pid}/stock", json={"delta": 100}, headers=auth_headers(role="customer"))
    assert r.status_code == 403


async def test_health(client):
    assert (await client.get(f"{BASE}/health")).json()["status"] == "healthy"
