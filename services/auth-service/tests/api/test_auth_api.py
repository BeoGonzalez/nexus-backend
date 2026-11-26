import pytest

from nexus_core.domain.exceptions import UnauthorizedException
from nexus_testkit import auth_headers, policy_password


async def test_app_imports_without_network():
    from auth_service.main import app

    assert "/api/v1/auth/login" in app.openapi()["paths"]


async def test_login_returns_tokens(client):
    r = await client.post("/api/v1/auth/login", json={"email": "a@b.cl", "password": "secret1"})
    assert r.status_code == 200
    assert r.json()["access_token"] == "acc"


async def test_login_with_invalid_body_is_422(client):
    assert (await client.post("/api/v1/auth/login", json={"email": "bad"})).status_code == 422


async def test_login_with_rejected_credentials_is_401(client, idp):
    idp.fail_with = UnauthorizedException("Correo electrónico o contraseña incorrectos.")
    r = await client.post("/api/v1/auth/login", json={"email": "a@b.cl", "password": "secret1"})
    assert r.status_code == 401


async def test_register_returns_201_and_publishes(client, publisher):
    r = await client.post("/api/v1/auth/register", json={"name": "Ana", "email": "ana@b.cl", "password": policy_password()})
    assert r.status_code == 201
    assert r.json()["id"] == "sub-123"
    assert [k for k, _ in publisher.published] == ["user.registered"]


@pytest.mark.parametrize("path,body", [
    ("/api/v1/auth/confirm", {"email": "a@b.cl", "confirmation_code": "123456"}),
    ("/api/v1/auth/forgot-password", {"email": "a@b.cl"}),
    ("/api/v1/auth/reset-password", {"email": "a@b.cl", "confirmation_code": "123456", "new_password": policy_password()}),
])
async def test_account_flows_report_success(client, path, body):
    r = await client.post(path, json=body)
    assert r.status_code == 200
    assert r.json()["status"] == "success"


async def test_resend_code_takes_email_query_param(client, idp):
    r = await client.post("/api/v1/auth/resend-code", params={"email": "a@b.cl"})
    assert r.status_code == 200
    assert idp.calls == [("resend_confirmation_code", ("a@b.cl",))]


async def test_refresh_returns_new_access_token(client):
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": "r1"})
    assert r.status_code == 200
    assert r.json()["access_token"] == "acc2"


async def test_me_returns_profile_from_token(client):
    r = await client.get("/api/v1/auth/me", headers=auth_headers(sub="u7", email="juan@b.cl", role="admin"))
    assert r.status_code == 200
    body = r.json()
    assert (body["id"], body["email"], body["name"], body["is_admin"]) == ("u7", "juan@b.cl", "Juan", True)


async def test_me_without_token_is_401(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_info_exposes_secret_presence_only_as_boolean(client):
    body = (await client.get("/api/v1/auth/info")).json()
    assert body["has_client_secret"] is False
    assert set(body) == {"auth_provider", "cognito_region", "cognito_user_pool_id",
                         "cognito_app_client_id", "has_client_secret"}


async def test_health_reports_cognito_not_configured_in_tests(client):
    body = (await client.get("/api/v1/auth/health")).json()
    assert body["status"] == "healthy"
    assert body["cognito_configured"] is False


async def test_register_existing_user_is_409_with_explicit_message(client, idp):
    from nexus_core.domain.exceptions import BusinessRuleViolationException

    idp.fail_with = BusinessRuleViolationException("Este usuario ya está registrado.")
    r = await client.post("/api/v1/auth/register", json={"name": "Ana", "email": "ana@b.cl", "password": policy_password()})
    assert r.status_code == 409
    assert r.json() == {"detail": "Este usuario ya está registrado."}
