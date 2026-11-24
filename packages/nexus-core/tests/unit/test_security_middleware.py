"""A06/A09: cabeceras de seguridad, CORS estricto, TrustedHost y logging de 401/403/429."""

import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from nexus_core.infrastructure.logging import setup_service_logging
from nexus_core.presentation.security import SecuritySettings, configure_service, install_security_middleware


def _app(settings: SecuritySettings) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/x/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/v1/x/item")
    async def item() -> dict:
        return {"ok": True}

    @app.get("/api/v1/x/private")
    async def private() -> dict:
        raise HTTPException(status_code=401, detail="no")

    @app.get("/api/v1/x/admin")
    async def admin() -> dict:
        raise HTTPException(status_code=403, detail="no")

    install_security_middleware(app, settings)
    return app


def _client(app: FastAPI, base_url: str = "http://api.nexus.test") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("203.0.113.7", 5000)), base_url=base_url)


@pytest.fixture
def settings() -> SecuritySettings:
    return SecuritySettings(cors_allowed_origins=["https://shop.nexus.test"], allowed_hosts=["api.nexus.test", "*.internal"])


async def test_security_headers_are_set(settings):
    async with _client(_app(settings)) as c:
        r = await c.get("/api/v1/x/item")
    assert r.headers["strict-transport-security"] == "max-age=63072000; includeSubDomains"
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-request-id"]


async def test_cors_does_not_reflect_unknown_origin(settings):
    async with _client(_app(settings)) as c:
        r = await c.get("/api/v1/x/item", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


async def test_cors_allows_configured_origin_with_credentials(settings):
    async with _client(_app(settings)) as c:
        r = await c.options(
            "/api/v1/x/item",
            headers={"Origin": "https://shop.nexus.test", "Access-Control-Request-Method": "GET"},
        )
    assert r.headers["access-control-allow-origin"] == "https://shop.nexus.test"
    assert r.headers["access-control-allow-credentials"] == "true"


def test_wildcard_origin_is_rejected():
    with pytest.raises(ValueError):
        SecuritySettings(cors_allowed_origins=["*"])


async def test_untrusted_host_is_rejected(settings):
    async with _client(_app(settings), base_url="http://evil.example") as c:
        r = await c.get("/api/v1/x/item")
    assert r.status_code == 400


async def test_wildcard_subdomain_host_is_trusted(settings):
    async with _client(_app(settings), base_url="http://catalog.internal") as c:
        r = await c.get("/api/v1/x/item")
    assert r.status_code == 200


async def test_kubelet_probe_with_pod_ip_host_reaches_health(settings):
    async with _client(_app(settings), base_url="http://10.0.3.25:8000") as c:
        r = await c.get("/api/v1/x/health")
    assert r.status_code == 200


@pytest.mark.parametrize("path, event", [("/api/v1/x/private", "http.unauthorized"), ("/api/v1/x/admin", "http.forbidden")])
async def test_401_and_403_emit_security_events(settings, capsys, path, event):
    setup_service_logging("svc-mw")
    async with _client(_app(settings)) as c:
        await c.get(path, headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln"})
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    events = [e for e in lines if e.get("security_event") == event]
    assert events, lines
    assert events[0]["path"] == path
    assert events[0]["client_ip"] == "203.0.113.7"
    assert "eyJhbGciOiJIUzI1NiJ9" not in json.dumps(lines)


async def test_configure_service_disables_api_docs_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    app = FastAPI()
    configure_service(app, "svc")
    async with _client(app) as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await c.get(path)).status_code == 404


async def test_configure_service_returns_generic_500_with_security_headers(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    app = FastAPI()

    @app.get("/boom")
    async def boom() -> dict:
        raise RuntimeError("password=hunter2 /app/src")

    configure_service(app, "svc")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.nexus.test") as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    assert "hunter2" not in r.text
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_oversized_request_body_is_rejected_with_413():
    app = FastAPI()

    @app.post("/api/v1/x/echo")
    async def echo(payload: dict) -> dict:
        return {"n": len(payload)}

    install_security_middleware(app, SecuritySettings(max_body_bytes=1024))
    async with _client(app) as c:
        big = await c.post("/api/v1/x/echo", json={"a": "A" * 5000})
        small = await c.post("/api/v1/x/echo", json={"a": "ok"})
    assert big.status_code == 413
    assert small.status_code == 200


async def test_chunked_body_without_content_length_is_also_limited():
    app = FastAPI()

    @app.post("/api/v1/x/echo")
    async def echo(payload: dict) -> dict:
        return {"n": len(payload)}

    install_security_middleware(app, SecuritySettings(max_body_bytes=1024))

    async def gen():
        yield b'{"a": "'
        for _ in range(10):
            yield b"A" * 500
        yield b'"}'

    async with _client(app) as c:
        r = await c.post("/api/v1/x/echo", content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 413
