"""A10: manejo fail-closed de condiciones excepcionales."""

import logging

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from nexus_core.domain.exceptions import (
    BusinessRuleViolationException,
    ForbiddenException,
    ResourceNotFoundException,
    UnauthorizedException,
)
from nexus_core.presentation.errors import install_exception_handlers

app = FastAPI()
install_exception_handlers(app)


class Login(BaseModel):
    email: str
    password: str
    age: int


@app.post("/login")
async def login(body: Login) -> dict:
    return {}


@app.get("/boom")
async def boom() -> dict:
    raise RuntimeError('SELECT * FROM users WHERE pass = "x" -- /app/services/secret_path.py')


@app.get("/raise/{kind}")
async def raise_kind(kind: str) -> dict:
    errors = {
        "notfound": ResourceNotFoundException("Producto no encontrado"),
        "conflict": BusinessRuleViolationException("Sin stock"),
        "unauth": UnauthorizedException("Token inválido"),
        "forbidden": ForbiddenException("Solo admin"),
        "http": HTTPException(status_code=418, detail="teapot"),
    }
    raise errors[kind]


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_unhandled_exception_returns_generic_500_without_internals(client, caplog):
    with caplog.at_level(logging.ERROR):
        r = await client.get("/boom", headers={"X-Request-ID": "req-12345"})
    assert r.status_code == 500
    body = r.json()
    assert body == {"detail": "Error interno del servidor.", "request_id": "req-12345"}
    assert "SELECT" not in r.text and "secret_path" not in r.text and "Traceback" not in r.text
    assert any(rec.exc_info for rec in caplog.records), "la traza completa debe ir al log"


async def test_validation_error_does_not_echo_the_submitted_input(client):
    r = await client.post("/login", json={"email": "a@b.cl", "password": "Sup3rS3cret!", "age": "x"})
    assert r.status_code == 422
    assert "Sup3rS3cret!" not in r.text
    detail = r.json()["detail"]
    assert detail and all(set(d) == {"loc", "msg", "type"} for d in detail)


async def test_malformed_json_is_422_without_echo(client):
    r = await client.post("/login", content=b'{"password": "Sup3rS3cret!",', headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert "Sup3rS3cret!" not in r.text


@pytest.mark.parametrize(
    "kind, status, detail",
    [
        ("notfound", 404, "Producto no encontrado"),
        ("conflict", 409, "Sin stock"),
        ("unauth", 401, "Token inválido"),
        ("forbidden", 403, "Solo admin"),
        ("http", 418, "teapot"),
    ],
)
async def test_domain_and_http_exceptions_map_to_status(client, kind, status, detail):
    r = await client.get(f"/raise/{kind}")
    assert r.status_code == status
    assert r.json()["detail"] == detail


async def test_unauthorized_sets_www_authenticate(client):
    r = await client.get("/raise/unauth")
    assert r.headers["www-authenticate"] == "Bearer"


async def test_generated_request_id_when_client_sends_none(client):
    r = await client.get("/boom")
    assert len(r.json()["request_id"]) >= 16
