from typing import Any

import httpx
import pytest

from auth_service.domain.ports import IdentityProviderPort
from nexus_testkit import FakePublisher


class FakeIdentityProvider(IdentityProviderPort):
    """IdP en memoria: registra llamadas y permite simular errores."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.calls: list[tuple[str, tuple]] = []

    def _call(self, name: str, *args):
        self.calls.append((name, args))
        if self.fail_with:
            raise self.fail_with

    async def authenticate(self, email, password) -> dict[str, Any]:
        self._call("authenticate", email, password)
        return {"access_token": "acc", "id_token": "idt", "refresh_token": "ref", "expires_in": 900}

    async def register(self, email, password, name) -> dict[str, Any]:
        self._call("register", email, password, name)
        return {"user_sub": "sub-123", "user_confirmed": False}

    async def confirm_signup(self, email, code) -> bool:
        self._call("confirm_signup", email, code)
        return True

    async def resend_confirmation_code(self, email) -> bool:
        self._call("resend_confirmation_code", email)
        return True

    async def refresh_tokens(self, refresh_token, email=None) -> dict[str, Any]:
        self._call("refresh_tokens", refresh_token, email)
        return {"access_token": "acc2", "id_token": "idt2"}

    async def forgot_password(self, email) -> bool:
        self._call("forgot_password", email)
        return True

    async def confirm_forgot_password(self, email, code, new_password) -> bool:
        self._call("confirm_forgot_password", email, code, new_password)
        return True



@pytest.fixture
def idp():
    return FakeIdentityProvider()


@pytest.fixture
def publisher():
    return FakePublisher()


@pytest.fixture
async def client(idp, publisher):
    from auth_service.application.services import AuthService
    from auth_service.main import app
    from auth_service.presentation.router import LIMITERS, get_auth_service

    for limiter in LIMITERS:
        limiter.reset()

    app.dependency_overrides[get_auth_service] = lambda: AuthService(idp=idp, publisher=publisher)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://auth") as c:
        yield c
    app.dependency_overrides.clear()
