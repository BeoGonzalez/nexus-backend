"""Hardening común en los 7 microservicios (A02, A06, A09, A10)."""

import importlib

import httpx
import pytest

SERVICES = [
    ("auth_service.main", "/api/v1/auth/health"),
    ("catalog_service.main", "/api/v1/catalog/health"),
    ("cart_service.main", "/api/v1/cart/health"),
    ("orders_service.main", "/api/v1/orders/health"),
    ("notifications_service.main", "/api/v1/notifications/health"),
    ("recommendations_service.main", "/api/v1/recommendations/health"),
    ("ai_agent_service.main", "/api/v1/assistant/health"),
]


def _app(module: str):
    return importlib.import_module(module).app


def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://api.nexus.test")


@pytest.mark.parametrize("module, health", SERVICES)
async def test_responses_carry_security_headers(module, health):
    async with _client(_app(module)) as c:
        r = await c.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert r.headers["strict-transport-security"]
    assert r.headers["x-request-id"]


@pytest.mark.parametrize("module, health", SERVICES)
async def test_api_docs_are_disabled(module, health):
    async with _client(_app(module)) as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await c.get(path)).status_code == 404


@pytest.mark.parametrize("module, health", SERVICES)
async def test_cors_never_reflects_arbitrary_origins(module, health):
    async with _client(_app(module)) as c:
        r = await c.options(health, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") not in ("*", "https://evil.example")


@pytest.mark.parametrize("module, health", SERVICES)
async def test_unhandled_errors_are_generic(module, health):
    app = _app(module)
    handler = app.exception_handlers.get(Exception)
    assert handler is not None, "falta el manejador global fail-closed"
