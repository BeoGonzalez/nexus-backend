import logging
from auth_service.application.dtos import (
    ConfirmSignUpRequest,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from auth_service.domain.ports import IdentityProviderPort
from nexus_events.publisher import EventPublisher
from nexus_events.schemas.users import UserRegisteredEvent

logger = logging.getLogger("auth.service")


class AuthService:
    def __init__(self, idp: IdentityProviderPort, publisher: EventPublisher | None = None) -> None:
        self._idp = idp
        self._publisher = publisher

    async def login(self, request: LoginRequest) -> TokenResponse:
        auth_data = await self._idp.authenticate(request.email, request.password)
        return TokenResponse(
            access_token=auth_data["access_token"],
            id_token=auth_data["id_token"],
            refresh_token=auth_data.get("refresh_token"),
            token_type=auth_data.get("token_type", "Bearer"),
            expires_in=auth_data.get("expires_in", 3600),
        )

    async def register(self, request: RegisterRequest) -> UserResponse:
        result = await self._idp.register(request.email, request.password, request.name)
        user_id = result.get("user_sub") or f"usr-{abs(hash(request.email)) % 100000}"
        is_confirmed = result.get("user_confirmed", False)

        # Publicar evento de usuario registrado a RabbitMQ para notificaciones de bienvenida
        if self._publisher:
            try:
                event = UserRegisteredEvent(
                    user_id=user_id,
                    email=request.email,
                    full_name=request.name,
                )
                await self._publisher.publish("user.registered", event)
            except Exception as exc:
                logger.warning("No se pudo publicar evento user.registered: %s", exc)

        return UserResponse(
            id=user_id,
            name=request.name,
            email=request.email,
            role="customer",
            is_admin=False,
            is_active=True,
            is_confirmed=is_confirmed,
        )

    async def confirm_signup(self, request: ConfirmSignUpRequest) -> dict[str, str]:
        await self._idp.confirm_signup(request.email, request.confirmation_code)
        return {"status": "success", "message": "Cuenta confirmada exitosamente en AWS Cognito."}

    async def resend_code(self, email: str) -> dict[str, str]:
        await self._idp.resend_confirmation_code(email)
        return {"status": "success", "message": "Código de verificación reenviado a tu correo."}

    async def refresh_tokens(self, request: RefreshTokenRequest) -> TokenResponse:
        data = await self._idp.refresh_tokens(request.refresh_token, request.email)
        return TokenResponse(
            access_token=data["access_token"],
            id_token=data["id_token"],
            refresh_token=data.get("refresh_token", request.refresh_token),
            token_type=data.get("token_type", "Bearer"),
            expires_in=data.get("expires_in", 3600),
        )

    async def forgot_password(self, email: str) -> dict[str, str]:
        await self._idp.forgot_password(email)
        return {"status": "success", "message": "Código de recuperación enviado a tu correo electrónico."}

    async def reset_password(self, request: ResetPasswordRequest) -> dict[str, str]:
        await self._idp.confirm_forgot_password(
            email=request.email,
            code=request.confirmation_code,
            new_password=request.new_password,
        )
        return {"status": "success", "message": "Contraseña restablecida exitosamente."}
