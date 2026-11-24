"""Batería de ataques contra los 7 microservicios (pentest automatizado en proceso, A01/A02/A05/A07/A10).

Cada ruta protegida se ataca con tokens manipulados; todas las rutas, con entradas hostiles. Si alguno de estos
tests falla, la API es explotable de esa forma por cualquiera que llame directamente a API Gateway.
"""

import base64
import importlib
import json
import time
import uuid

import httpx
import jwt
import pytest

from nexus_testkit import TEST_JWT_SECRET, sign_token

PROTECTED = [
    ("auth_service.main", "GET", "/api/v1/auth/me", None),
    ("cart_service.main", "GET", "/api/v1/cart", None),
    ("orders_service.main", "GET", "/api/v1/orders", None),
    ("orders_service.main", "POST", "/api/v1/orders", {"items": [{"product_id": str(uuid.uuid4()), "quantity": 1}]}),
    ("recommendations_service.main", "GET", "/api/v1/recommendations/for-you", None),
    ("notifications_service.main", "POST", "/api/v1/notifications/send-receipt",
     {"order_id": str(uuid.uuid4()), "customer_email": "a@b.cl"}),
    ("ai_agent_service.main", "POST", "/api/v1/assistant/chat", {"query": "hola"}),
]
ADMIN_ONLY = [
    ("catalog_service.main", "POST", "/api/v1/catalog/products",
     {"title": "Gratis", "description": "x", "price_clp": 1, "stock": 1}),
    ("catalog_service.main", "PATCH", f"/api/v1/catalog/products/{uuid.uuid4()}/stock", {"delta": 1000}),
    ("notifications_service.main", "POST", "/api/v1/notifications/email",
     {"recipient": "victima@x.cl", "subject": "s", "body_html": "<a href=http://phish>x</a>"}),
]
ALL_APPS = sorted({m for m, *_ in PROTECTED + ADMIN_ONLY})


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _forged_tokens() -> dict[str, str]:
    now = int(time.time())
    claims = {"sub": "attacker", "role": "admin", "email": "a@b.cl", "email_verified": True, "exp": now + 3600}
    return {
        "alg_none": f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}.",
        "wrong_secret": jwt.encode(claims, "secreto-adivinado", algorithm="HS256"),
        "default_secret": jwt.encode(claims, "super-secret-jwt-key-for-local-development", algorithm="HS256"),
        "expired": sign_token(exp_delta_s=-60),
        "tampered_payload": (lambda t: f"{t.split('.')[0]}.{_b64(claims)}.{t.split('.')[2]}")(sign_token()),
        "empty_signature": (lambda t: t.rsplit(".", 1)[0] + ".")(sign_token()),
        "garbage": "not.a.jwt",
        "hs512_same_secret": jwt.encode(claims, TEST_JWT_SECRET + "x", algorithm="HS512"),
    }


def _client(module: str) -> httpx.AsyncClient:
    app = importlib.import_module(module).app
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://api.nexus.test")


async def _call(module, method, path, body, headers=None):
    async with _client(module) as c:
        return await c.request(method, path, json=body, headers=headers or {})


# ------------------------------------------------------------------------------------- A07: autenticación
@pytest.mark.parametrize("module, method, path, body", PROTECTED + ADMIN_ONLY)
@pytest.mark.parametrize("kind", list(_forged_tokens()))
async def test_forged_or_invalid_tokens_are_rejected(module, method, path, body, kind):
    token = _forged_tokens()[kind]
    r = await _call(module, method, path, body, {"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, f"{kind} aceptado en {method} {path}: {r.status_code}"


@pytest.mark.parametrize("module, method, path, body", PROTECTED + ADMIN_ONLY)
async def test_identity_headers_without_token_are_ignored(module, method, path, body):
    r = await _call(module, method, path, body, {"X-User-Id": "admin", "X-User-Role": "admin", "X-User-Email": "a@b.cl"})
    assert r.status_code == 401


# ------------------------------------------------------------------------------------- A01: control de acceso
@pytest.mark.parametrize("module, method, path, body", ADMIN_ONLY)
async def test_customer_cannot_use_admin_operations(module, method, path, body):
    r = await _call(module, method, path, body, {"Authorization": f"Bearer {sign_token(role='customer')}"})
    assert r.status_code == 403


@pytest.mark.parametrize("module, method, path, body", ADMIN_ONLY)
async def test_role_claim_in_token_cannot_be_self_assigned_without_signature(module, method, path, body):
    """Un usuario que edita su propio token para ponerse role=admin (sin la clave) queda fuera."""
    token = sign_token(role="customer")
    header, _, sig = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    payload["role"] = "admin"
    r = await _call(module, method, path, body, {"Authorization": f"Bearer {header}.{_b64(payload)}.{sig}"})
    assert r.status_code == 401


# ------------------------------------------------------------------------------------- A05/A10: entradas hostiles
HOSTILE_PATHS = [
    "/api/v1/catalog/products/../../../etc/passwd",
    "/api/v1/catalog/products/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/api/v1/catalog/products/1' OR '1'='1",
    "/api/v1/catalog/products/{{7*7}}",
    "/api/v1/orders/;cat%20/etc/passwd",
]


@pytest.mark.parametrize("path", HOSTILE_PATHS)
async def test_hostile_paths_never_cause_server_errors_or_leaks(path):
    module = "orders_service.main" if "/orders/" in path else "catalog_service.main"
    r = await _call(module, "GET", path, None, {"Authorization": f"Bearer {sign_token()}"})
    assert r.status_code in (400, 401, 404, 405, 422)
    assert "root:" not in r.text and "49" not in r.text.replace("4.9", "")


@pytest.mark.parametrize("module", ALL_APPS)
async def test_malformed_json_returns_422_without_internals(module):
    async with _client(module) as c:
        r = await c.post("/api/v1/x", content=b'{"a":', headers={"content-type": "application/json"})
    assert r.status_code in (404, 405, 422)
    assert "Traceback" not in r.text and "File \"" not in r.text


@pytest.mark.parametrize("module, method, path, body", PROTECTED)
async def test_huge_json_bodies_do_not_crash_services(module, method, path, body):
    if method != "POST":
        pytest.skip("solo rutas con cuerpo")
    bomb = {**(body or {}), "padding": "A" * 2_000_000}
    r = await _call(module, method, path, bomb, {"Authorization": f"Bearer {sign_token()}"})
    assert r.status_code == 413


@pytest.mark.parametrize("module", ALL_APPS)
async def test_server_banner_and_framework_details_are_not_exposed(module):
    async with _client(module) as c:
        r = await c.get("/does-not-exist")
    assert "server" not in {k.lower() for k in r.headers} or "uvicorn" not in r.headers.get("server", "").lower()
    assert "x-powered-by" not in {k.lower() for k in r.headers}
    for path in ("/docs", "/redoc", "/openapi.json"):
        async with _client(module) as c:
            assert (await c.get(path)).status_code == 404
