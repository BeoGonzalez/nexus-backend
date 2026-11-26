import pytest
from pydantic import ValidationError

from auth_service.application.dtos import (
    ConfirmSignUpRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
)


# Misma longitud mínima que el User Pool (terraform auth.tf: minimum_length = 12).
@pytest.mark.parametrize("password", ["", "1234567", "Abcdef1!xyz"])
def test_register_requires_password_of_at_least_12_chars(password):
    with pytest.raises(ValidationError):
        RegisterRequest(name="Ana", email="a@b.cl", password=password)


def test_reset_password_requires_new_password_of_at_least_12_chars():
    with pytest.raises(ValidationError):
        ResetPasswordRequest(email="a@b.cl", confirmation_code="123456", new_password="Abcdef1!xyz")


@pytest.mark.parametrize("code", ["12345", "1234567"])
def test_confirmation_code_must_have_exactly_6_chars(code):
    with pytest.raises(ValidationError):
        ConfirmSignUpRequest(email="a@b.cl", confirmation_code=code)


@pytest.mark.parametrize("email", ["no-at-sign", "a@", "@b.cl"])
def test_login_rejects_malformed_email(email):
    with pytest.raises(ValidationError):
        LoginRequest(email=email, password="secret1")
