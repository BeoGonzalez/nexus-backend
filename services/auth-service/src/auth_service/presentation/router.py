from fastapi import APIRouter, Depends, Request, status
from auth_service.application.dtos import (
    AuthInfoResponse,
    ConfirmSignUpRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from auth_service.application.services import AuthService
from auth_service.config import get_settings
from auth_service.infrastructure.cognito import CognitoAdapter
from nexus_core.domain.exceptions import UnauthorizedException
from nexus_core.infrastructure.logging import log_security_event
from nexus_events.publisher import EventPublisher
from nexus_security.dependencies import get_current_user
from nexus_security.jwt import TokenPayload
from nexus_security.rate_limit import SlidingWindowRateLimiter, client_ip, rate_limit

router = APIRouter(prefix="/api/v1/auth", tags=["Auth Service (AWS Cognito)"])
settings = get_settings()

_idp_adapter = CognitoAdapter()

# A07: límites por pod (API Gateway aplica el throttling global). Por email frena credential stuffing aunque se
# roten IPs; por IP frena el barrido de muchos emails desde un mismo origen.
EMAIL_LIMITER = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)
IP_LIMITER = SlidingWindowRateLimiter(max_requests=20, window_seconds=60)
LIMITERS = (EMAIL_LIMITER, IP_LIMITER)


def _limited(scope: str) -> list:
    return [Depends(rate_limit(scope, per_email=EMAIL_LIMITER, per_ip=IP_LIMITER))]


def get_auth_service() -> AuthService:
    publisher = EventPublisher(settings.EVENTS_TOPIC_ARN, region=settings.AWS_REGION) if settings.EVENTS_TOPIC_ARN else None
    return AuthService(idp=_idp_adapter, publisher=publisher)


@router.post("/login", response_model=TokenResponse, dependencies=_limited("auth.login"))
async def login(
    request: LoginRequest,
    http_request: Request,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Inicia sesión autenticando contra AWS Cognito (USER_PASSWORD_AUTH) y retorna tokens JWT."""
    try:
        return await service.login(request)
    except UnauthorizedException:
        log_security_event("auth.login_failed", email=str(request.email), client_ip=client_ip(http_request))
        raise


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, dependencies=_limited("auth.register"))
async def register(
    request: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Registra un nuevo usuario en el User Pool de AWS Cognito."""
    return await service.register(request)


@router.post("/confirm", dependencies=_limited("auth.confirm"))
async def confirm_account(
    request: ConfirmSignUpRequest,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """Confirma el código de 6 dígitos enviado al correo por AWS Cognito."""
    return await service.confirm_signup(request)


@router.post("/resend-code", dependencies=_limited("auth.resend_code"))
async def resend_code(
    email: str,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """Reenvía el código de confirmación de cuenta."""
    return await service.resend_code(email)


@router.post("/refresh", response_model=TokenResponse, dependencies=_limited("auth.refresh"))
async def refresh_tokens(
    request: RefreshTokenRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Renueva los tokens de acceso expirados utilizando el Refresh Token de AWS Cognito."""
    return await service.refresh_tokens(request)


@router.post("/forgot-password", dependencies=_limited("auth.forgot_password"))
async def forgot_password(
    request: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """Inicia el proceso de restablecimiento de contraseña en AWS Cognito."""
    return await service.forgot_password(request.email)


@router.post("/reset-password", dependencies=_limited("auth.reset_password"))
async def reset_password(
    request: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """Establece la nueva contraseña usando el código recibido por correo."""
    return await service.reset_password(request)


@router.get("/me", response_model=UserResponse)
async def me(current_user: TokenPayload = Depends(get_current_user)) -> UserResponse:
    """Obtiene el perfil del usuario autenticado a través de AWS API Gateway o Bearer JWT."""
    return UserResponse(
        id=current_user.sub,
        name=current_user.email.split("@")[0].capitalize() if current_user.email else "Gamer",
        email=current_user.email or "usuario@nexus.cl",
        role=current_user.role,
        is_admin=current_user.role == "admin",
        is_active=True,
        is_confirmed=True,
    )


@router.get("/info", response_model=AuthInfoResponse)
async def auth_info() -> AuthInfoResponse:
    """Retorna la configuración activa de AWS Cognito."""
    return AuthInfoResponse(
        auth_provider="Amazon Web Services (AWS Cognito)",
        cognito_region=settings.COGNITO_REGION,
        cognito_user_pool_id=settings.COGNITO_USER_POOL_ID or "local-dev-pool",
        cognito_app_client_id=settings.COGNITO_APP_CLIENT_ID or "local-app-client",
        has_client_secret=bool(settings.COGNITO_APP_CLIENT_SECRET),
    )


@router.get("/health")
async def health_check() -> dict:
    return {
        "status": "healthy",
        "service": "auth-service",
        "cognito_configured": _idp_adapter.is_configured,
        "region": settings.COGNITO_REGION,
    }
