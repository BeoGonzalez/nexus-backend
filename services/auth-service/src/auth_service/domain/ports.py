from abc import ABC, abstractmethod
from typing import Any
from auth_service.domain.entities import User


class UserRepositoryPort(ABC):
    @abstractmethod
    async def get_by_id(self, user_id: str) -> User | None:
        ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None:
        ...

    @abstractmethod
    async def save(self, user: User) -> User:
        ...


class IdentityProviderPort(ABC):
    """Puerto abstracto para integración con Proveedores de Identidad (AWS Cognito)."""

    @abstractmethod
    async def authenticate(self, email: str, password: str) -> dict[str, Any]:
        """Autentica contra Cognito (USER_PASSWORD_AUTH) y retorna id_token, access_token y refresh_token."""
        ...

    @abstractmethod
    async def register(self, email: str, password: str, name: str) -> dict[str, Any]:
        """Registra un usuario en el Cognito User Pool."""
        ...

    @abstractmethod
    async def confirm_signup(self, email: str, code: str) -> bool:
        """Confirma el código de verificación por correo en Cognito."""
        ...

    @abstractmethod
    async def resend_confirmation_code(self, email: str) -> bool:
        """Reenvía el código de verificación."""
        ...

    @abstractmethod
    async def refresh_tokens(self, refresh_token: str, email: str | None = None) -> dict[str, Any]:
        """Renueva el token de acceso expirado usando REFRESH_TOKEN_AUTH."""
        ...

    @abstractmethod
    async def forgot_password(self, email: str) -> bool:
        """Inicia el flujo de recuperación de contraseña en Cognito."""
        ...

    @abstractmethod
    async def confirm_forgot_password(self, email: str, code: str, new_password: str) -> bool:
        """Confirma la nueva contraseña mediante el código de recuperación."""
        ...

    @abstractmethod
    async def get_user_from_token(self, token: str) -> dict[str, Any]:
        """Decodifica y valida las credenciales o atributos del usuario."""
        ...
