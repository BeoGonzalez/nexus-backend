import pytest

from auth_service.application.dtos import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
)
from auth_service.application.services import AuthService
from nexus_core.domain.exceptions import UnauthorizedException
from nexus_events.schemas.users import UserRegisteredEvent
from nexus_testkit import FakePublisher


async def test_login_returns_tokens_from_identity_provider(idp):
    tokens = await AuthService(idp).login(LoginRequest(email="a@b.cl", password="secret1"))
    assert (tokens.access_token, tokens.id_token, tokens.refresh_token, tokens.expires_in) == ("acc", "idt", "ref", 900)
    assert idp.calls == [("authenticate", ("a@b.cl", "secret1"))]


async def test_register_publishes_user_registered_with_idp_subject(idp, publisher):
    user = await AuthService(idp, publisher).register(RegisterRequest(name="Ana", email="ana@b.cl", password="12345678"))
    assert user.id == "sub-123"
    assert user.is_confirmed is False
    [(key, event)] = publisher.published
    assert key == "user.registered"
    assert isinstance(event, UserRegisteredEvent)
    assert (event.user_id, event.email, event.full_name) == ("sub-123", "ana@b.cl", "Ana")


async def test_register_succeeds_even_if_broker_is_down(idp):
    user = await AuthService(idp, FakePublisher(fail=True)).register(
        RegisterRequest(name="Ana", email="ana@b.cl", password="12345678")
    )
    assert user.email == "ana@b.cl"


async def test_refresh_keeps_original_refresh_token_when_idp_omits_it(idp):
    tokens = await AuthService(idp).refresh_tokens(RefreshTokenRequest(refresh_token="r-old", email="a@b.cl"))
    assert tokens.access_token == "acc2"
    assert tokens.refresh_token == "r-old"


async def test_reset_password_forwards_code_and_new_password(idp):
    await AuthService(idp).reset_password(
        ResetPasswordRequest(email="a@b.cl", confirmation_code="123456", new_password="newpass99")
    )
    assert idp.calls == [("confirm_forgot_password", ("a@b.cl", "123456", "newpass99"))]


async def test_identity_provider_errors_propagate(idp):
    idp.fail_with = UnauthorizedException("bad creds")
    with pytest.raises(UnauthorizedException):
        await AuthService(idp).login(LoginRequest(email="a@b.cl", password="secret1"))
