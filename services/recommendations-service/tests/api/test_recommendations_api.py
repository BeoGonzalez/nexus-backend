import pytest

from nexus_testkit import auth_headers

BASE = "/api/v1/recommendations"


async def test_app_imports_without_network():
    from recommendations_service.main import app

    assert f"{BASE}/for-you" in app.openapi()["paths"]


async def test_for_you_requires_authentication(client):
    assert (await client.get(f"{BASE}/for-you")).status_code == 401


async def test_for_you_uses_token_subject(client, store):
    r = await client.get(f"{BASE}/for-you", params={"limit": 2}, headers=auth_headers(sub="alice"))
    assert r.status_code == 200
    assert [x["title"] for x in r.json()] == ["Hades II", "Celeste"]
    assert store.calls == [("user", "alice", 2)]


async def test_trending_is_public(client):
    r = await client.get(f"{BASE}/trending")
    assert [x["title"] for x in r.json()] == ["Elden Ring", "Balatro"]


@pytest.mark.parametrize("limit", [0, 21])
async def test_limit_out_of_range_is_422(client, limit):
    assert (await client.get(f"{BASE}/trending", params={"limit": limit})).status_code == 422


async def test_health(client):
    assert (await client.get(f"{BASE}/health")).json()["status"] == "healthy"
