import pytest
from pydantic import ValidationError

from auth_service.application.dtos import ConfirmSignUpRequest, LoginRequest, RegisterRequest


@pytest.mark.parametrize("password", ["", "1234567"])
def test_register_requires_password_of_at_least_8_chars(password):
    with pytest.raises(ValidationError):
        RegisterRequest(name="Ana", email="a@b.cl", password=password)


@pytest.mark.parametrize("code", ["12345", "1234567"])
def test_confirmation_code_must_have_exactly_6_chars(code):
    with pytest.raises(ValidationError):
        ConfirmSignUpRequest(email="a@b.cl", confirmation_code=code)


@pytest.mark.parametrize("email", ["no-at-sign", "a@", "@b.cl"])
def test_login_rejects_malformed_email(email):
    with pytest.raises(ValidationError):
        LoginRequest(email=email, password="secret1")
