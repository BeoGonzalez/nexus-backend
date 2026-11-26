import uuid

import httpx
import pytest
from fastapi import Depends, FastAPI

from nexus_security import dependencies
from nexus_security.dependencies import get_cart_owner, get_current_user
from nexus_security.jwt import TokenPayload
from nexus_security.permissions import require_role
from nexus_testkit import auth_headers, sign_token

app = FastAPI()


@app.get("/who")
async def who(user: TokenPayload = Depends(get_current_user)) -> dict:
    return user.model_dump()


@app.get("/cart-owner")
async def cart_owner(owner: str = Depends(get_cart_owner)) -> dict:
    return {"owner": owner}


@app.get("/admin-only")
async def admin_only(user: TokenPayload = Depends(require_role("admin"))) -> dict:
    return {"sub": user.sub}


@app.get("/editor-only")
async def editor_only(user: TokenPayload = Depends(require_role("editor"))) -> dict:
    return {"sub": user.sub}


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_valid_bearer_token_identifies_user(client):
    r = await client.get("/who", headers=auth_headers(sub="u42", email="a@b.cl"))
    assert r.status_code == 200
    assert r.json()["sub"] == "u42"
    assert r.json()["email"] == "a@b.cl"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic dXNlcjpwYXNz"}, {"Authorization": "Bearer"}])
async def test_missing_or_non_bearer_authorization_is_401(client, headers):
    assert (await client.get("/who", headers=headers)).status_code == 401


async def test_expired_token_is_401(client):
    r = await client.get("/who", headers={"Authorization": f"Bearer {sign_token(exp_delta_s=-5)}"})
    assert r.status_code == 401


async def test_identity_headers_from_the_client_are_ignored(client):
    """Antes X-User-* se aceptaba sin verificacion: cualquiera se hacia pasar por otro (o por admin)."""
    r = await client.get("/who", headers={"X-User-Id": "u9", "X-User-Role": "admin"})
    assert r.status_code == 401


async def test_identity_headers_cannot_override_a_valid_token(client):
    headers = {**auth_headers(sub="u1", role="customer"), "X-User-Id": "victim", "X-User-Role": "admin"}
    r = await client.get("/who", headers=headers)
    assert r.json()["sub"] == "u1"
    assert r.json()["role"] == "customer"


async def test_customer_cannot_reach_admin_route(client):
    assert (await client.get("/admin-only", headers=auth_headers(role="customer"))).status_code == 403


async def test_admin_reaches_admin_route(client):
    assert (await client.get("/admin-only", headers=auth_headers(role="admin"))).status_code == 200


async def test_admin_bypasses_any_required_role(client):
    assert (await client.get("/editor-only", headers=auth_headers(role="admin"))).status_code == 200


async def test_role_route_without_credentials_is_401(client):
    assert (await client.get("/admin-only")).status_code == 401


async def test_admin_header_does_not_grant_admin(client):
    r = await client.get("/admin-only", headers={**auth_headers(role="customer"), "X-User-Role": "admin"})
    assert r.status_code == 403


# ------------------------------ Carrito: dueño ------------------------------
async def test_cart_owner_is_token_sub(client):
    r = await client.get("/cart-owner", headers=auth_headers(sub="u7"))
    assert r.json() == {"owner": "u7"}


async def test_cart_owner_for_guest_is_prefixed_uuid(client):
    gid = str(uuid.uuid4())
    r = await client.get("/cart-owner", headers={"X-Guest-Id": gid})
    assert r.json() == {"owner": f"guest:{gid}"}


async def test_token_wins_over_guest_id(client):
    r = await client.get("/cart-owner", headers={**auth_headers(sub="u7"), "X-Guest-Id": str(uuid.uuid4())})
    assert r.json() == {"owner": "u7"}


@pytest.mark.parametrize("guest", ["user-sub-of-someone", "../../etc", "", "guest:" + str(uuid.uuid4())])
async def test_non_uuid_guest_id_is_401(client, guest):
    assert (await client.get("/cart-owner", headers={"X-Guest-Id": guest})).status_code == 401


async def test_cart_owner_ignores_x_user_id(client):
    assert (await client.get("/cart-owner", headers={"X-User-Id": "victim"})).status_code == 401


# ------------------------------ Modo Cognito ------------------------------
async def test_cognito_mode_uses_the_cognito_verifier(client, monkeypatch):
    seen = {}

    class FakeVerifier:
        def verify(self, token):
            seen["token"] = token
            return TokenPayload(sub="cog-1", email="c@nexus.cl", role="admin", exp=9999999999)

    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_X")
    monkeypatch.setenv("COGNITO_APP_CLIENT_ID", "client")
    monkeypatch.setattr(dependencies, "get_cognito_verifier", lambda *a: FakeVerifier())

    r = await client.get("/who", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 200
    assert r.json()["sub"] == "cog-1"
    assert seen["token"] == "abc.def.ghi"


async def test_cognito_mode_rejects_local_hs256_tokens(client, monkeypatch):
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_X")
    monkeypatch.setenv("COGNITO_APP_CLIENT_ID", "client")
    from nexus_security.cognito import CognitoJwtVerifier

    class NoNetworkJwks:
        def get_signing_key_from_jwt(self, token):
            raise jwt_error()

    def jwt_error():
        import jwt

        return jwt.PyJWKClientError("sin red en tests")

    monkeypatch.setattr(
        dependencies, "get_cognito_verifier",
        lambda region, pool, client_id: CognitoJwtVerifier(region, pool, client_id, jwks_client=NoNetworkJwks()),
    )
    assert (await client.get("/who", headers=auth_headers(role="admin"))).status_code == 401


async def test_without_cognito_and_without_jwt_secret_every_token_is_rejected(client, monkeypatch):
    """Fail-closed: antes se caía a un secreto por defecto conocido públicamente."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    forged = sign_token(secret="super-secret-jwt-key-for-local-development")
    r = await client.get("/who", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_admin_route_access_is_audited(client, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="nexus.security"):
        await client.get("/admin-only", headers=auth_headers(sub="admin-7", role="admin"))
    events = [r for r in caplog.records if getattr(r, "security_event", None) == "authz.admin_access"]
    assert events and events[0].user_sub == "admin-7" and events[0].required_role == "admin"


async def test_role_denial_is_audited_with_subject(client, caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="nexus.security"):
        r = await client.get("/admin-only", headers=auth_headers(sub="cust-9", role="customer"))
    assert r.status_code == 403
    events = [r for r in caplog.records if getattr(r, "security_event", None) == "authz.denied"]
    assert events and events[0].user_sub == "cust-9"


async def test_placeholder_cognito_env_falls_back_to_local_hs256(client, monkeypatch):
    # Valores tal cual vienen en .env.example: deben comportarse como "sin Cognito".
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_xxxxxxxxx")
    monkeypatch.setenv("COGNITO_APP_CLIENT_ID", "xxxxxxxxxxxxxxxxxxxxxxxxxx")
    monkeypatch.setattr(
        dependencies, "get_cognito_verifier", lambda *a: pytest.fail("no debe usar el verificador de Cognito")
    )

    r = await client.get("/who", headers=auth_headers(sub="local-1"))
    assert r.status_code == 200
    assert r.json()["sub"] == "local-1"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("us-east-1_xxxxxxxxx", True),
        ("XXXXXXXXXXXXXXXXXXXXXXXXXX", True),
        ("your-user-pool-id", True),
        ("us-east-1_AbC123dEf", False),
        ("4j2k8l1m9n0p3q5r7s6t", False),
    ],
)
def test_is_placeholder_credential(value, expected):
    from nexus_security.cognito import is_placeholder_credential

    assert is_placeholder_credential(value) is expected
