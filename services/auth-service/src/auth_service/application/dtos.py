from pydantic import BaseModel, EmailStr, Field

# Igual que el User Pool de Cognito (nexus-infrastructure/terraform/auth.tf: minimum_length).
PASSWORD_MIN_LENGTH = 12


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH)


class ConfirmSignUpRequest(BaseModel):
    email: EmailStr
    confirmation_code: str = Field(..., min_length=6, max_length=6)


class ResendCodeRequest(BaseModel):
    email: EmailStr


class RefreshTokenRequest(BaseModel):
    refresh_token: str
    email: EmailStr | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    confirmation_code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH)


class TokenResponse(BaseModel):
    access_token: str
    id_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_in: int = 3600

    @property
    def token(self) -> str:
        """Alias de compatibilidad para clientes que esperan un único token."""
        return self.id_token or self.access_token


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str = "customer"
    is_admin: bool = False
    is_active: bool = True
    is_confirmed: bool = True
    image: str | None = None


class AuthInfoResponse(BaseModel):
    auth_provider: str
    cognito_region: str
    cognito_user_pool_id: str
    cognito_app_client_id: str
    has_client_secret: bool
