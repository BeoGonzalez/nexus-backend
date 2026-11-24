import pytest
from httpx import ASGITransport, AsyncClient

from auth_service.application.dtos import (
    ConfirmSignUpRequest,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
)
from auth_service.application.services import AuthService
from auth_service.domain.ports import IdentityProviderPort
from auth_service.infrastructure.cognito import CognitoAdapter, calculate_secret_hash
from auth_service.main import app
from nexus_security.dependencies import get_current_user
from nexus_security.jwt import decode_access_token


class MockCognitoIdentityProvider(IdentityProviderPort):
    def __init__(self) -> None:
        self.users = {}

    async def authenticate(self, email: str, password: str) -> dict:
        import jwt
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        payload = {
            "sub": f"cognito-sub-{email}",
            "email": email,
            "role": "customer",
            "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TestPool",
            "exp": int((now + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(payload, "a-very-secure-32-byte-secret-key-nexus", algorithm="HS256")
        return {
            "access_token": token,
            "id_token": token,
            "refresh_token": f"refresh-{email}",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

    async def register(self, email: str, password: str, name: str) -> dict:
        user_id = f"cognito-sub-{email}"
        self.users[email] = {"id": user_id, "name": name, "confirmed": False}
        return {"user_sub": user_id, "user_confirmed": False}

    async def confirm_signup(self, email: str, code: str) -> bool:
        if email in self.users and code == "123456":
            self.users[email]["confirmed"] = True
            return True
        return True

    async def resend_confirmation_code(self, email: str) -> bool:
        return True

    async def refresh_tokens(self, refresh_token: str, email: str | None = None) -> dict:
        return await self.authenticate(email or "refresh@nexus.cl", "mock")

    async def forgot_password(self, email: str) -> bool:
        return True

    async def confirm_forgot_password(self, email: str, code: str, new_password: str) -> bool:
        return True

    async def get_user_from_token(self, token: str) -> dict:
        payload = decode_access_token(token, "a-very-secure-32-byte-secret-key-nexus", "HS256")
        return {"sub": payload.sub, "email": payload.email, "role": payload.role}


def test_calculate_secret_hash():
    # Valida el algoritmo HMAC-SHA256 exigido por AWS Cognito
    username = "gamer@nexus.cl"
    client_id = "test-app-client-123"
    client_secret = "test-app-client-secret-456"
    
    secret_hash = calculate_secret_hash(username, client_id, client_secret)
    assert secret_hash is not None
    assert len(secret_hash) > 20
    # Determinismo
    assert secret_hash == calculate_secret_hash(username, client_id, client_secret)


@pytest.mark.asyncio
async def test_auth_login_generates_cognito_tokens():
    idp = MockCognitoIdentityProvider()
    service = AuthService(idp)

    req = LoginRequest(email="gamer@nexus.cl", password="Password123!")
    token_resp = await service.login(req)

    assert token_resp.id_token is not None
    assert token_resp.access_token is not None
    assert token_resp.refresh_token == "refresh-gamer@nexus.cl"
    assert token_resp.expires_in == 3600

    payload = decode_access_token(token_resp.id_token, "a-very-secure-32-byte-secret-key-nexus", "HS256")
    assert payload.email == "gamer@nexus.cl"
    assert "cognito-sub" in payload.sub


@pytest.mark.asyncio
async def test_auth_register_and_confirm_cognito_user():
    idp = MockCognitoIdentityProvider()
    service = AuthService(idp)

    # 1. Registro
    req = RegisterRequest(name="Master Chief", email="chief@unsc.gov", password="StrongPassword123!")
    resp = await service.register(req)

    assert resp.email == "chief@unsc.gov"
    assert resp.name == "Master Chief"
    assert resp.is_confirmed is False

    # 2. Confirmación con código de correo
    confirm_resp = await service.confirm_signup(
        ConfirmSignUpRequest(email="chief@unsc.gov", confirmation_code="123456")
    )
    assert confirm_resp["status"] == "success"


@pytest.mark.asyncio
async def test_auth_refresh_tokens():
    idp = MockCognitoIdentityProvider()
    service = AuthService(idp)

    req = RefreshTokenRequest(refresh_token="ref-token-xyz", email="refreshed@nexus.cl")
    refreshed = await service.refresh_tokens(req)

    assert refreshed.id_token is not None
    assert refreshed.access_token is not None


@pytest.mark.asyncio
async def test_get_current_user_requires_a_token_gateway_headers_are_not_identity():
    # Antes X-User-* (supuestamente puestas por API Gateway) bastaban para autenticarse: el BFF las
    # reenviaba desde el navegador y cualquiera podia hacerse pasar por otro. Ahora solo vale el JWT.
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await get_current_user(authorization=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_cognito_adapter_local_fallback_when_no_credentials():
    adapter = CognitoAdapter()
    assert adapter.is_configured is False

    # En local dev sin AWS, funciona en modo mock determinista
    reg = await adapter.register("local_dev@nexus.cl", "Secret123!", "Dev User")
    assert reg["user_confirmed"] is True

    auth = await adapter.authenticate("local_dev@nexus.cl", "Secret123!")
    assert auth["id_token"] is not None
    assert auth["token_type"] == "Bearer"


@pytest.mark.asyncio
async def test_auth_fastapi_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Info endpoint
        info_resp = await client.get("/api/v1/auth/info")
        assert info_resp.status_code == 200
        assert "AWS Cognito" in info_resp.json()["auth_provider"]

        # 2. Health endpoint
        health_resp = await client.get("/api/v1/auth/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "healthy"

        # 3. Registro + login (el modo local ya no acepta usuarios no registrados)
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={"name": "FastAPI User", "email": "fastapi_user@nexus.cl", "password": "Password123!"},
        )
        assert reg_resp.status_code == 201
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "fastapi_user@nexus.cl", "password": "Password123!"},
        )
        assert login_resp.status_code == 200
        data = login_resp.json()
        assert "id_token" in data
        assert "access_token" in data
