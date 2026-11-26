"""Dependencias FastAPI de identidad.

La identidad sale SOLO de un token verificado:
- Modo Cognito (COGNITO_USER_POOL_ID y COGNITO_APP_CLIENT_ID definidos): JWT RS256 del User Pool.
- Modo local (sin Cognito; tests y desarrollo): JWT HS256 firmado con JWT_SECRET.

Las cabeceras X-User-Id / X-User-Email / X-User-Role NO se aceptan: el cliente las controla.
"""

import os
import uuid
from functools import lru_cache

from fastapi import Header, HTTPException, status

from nexus_core.domain.exceptions import UnauthorizedException
from nexus_core.infrastructure.logging import log_security_event
from nexus_security.cognito import CognitoJwtVerifier, cognito_settings_present
from nexus_security.jwt import TokenPayload, decode_access_token

GUEST_PREFIX = "guest:"


@lru_cache(maxsize=4)
def get_cognito_verifier(region: str, user_pool_id: str, client_id: str) -> CognitoJwtVerifier:
    return CognitoJwtVerifier(region, user_pool_id, client_id)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_token(token: str) -> TokenPayload:
    pool = os.getenv("COGNITO_USER_POOL_ID", "").strip()
    client_id = os.getenv("COGNITO_APP_CLIENT_ID", "").strip()
    try:
        if cognito_settings_present(pool, client_id):
            region = os.getenv("COGNITO_REGION", "").strip() or pool.split("_", 1)[0]
            return get_cognito_verifier(region, pool, client_id).verify(token)
        secret = os.getenv("JWT_SECRET", "").strip()
        if not secret:
            # Fail-closed (A07): sin Cognito ni secreto explícito no hay forma segura de verificar tokens.
            log_security_event("auth.misconfigured", reason="sin Cognito ni JWT_SECRET")
            raise UnauthorizedException("Autenticación no configurada.")
        algo = os.getenv("JWT_ALGORITHM", "HS256")
        return decode_access_token(token, secret, algo)
    except UnauthorizedException as exc:
        raise _unauthorized(str(exc)) from exc


def _bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


async def get_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
) -> TokenPayload:
    token = _bearer(authorization)
    if token is None:
        raise _unauthorized("Falta cabecera de autorización Bearer.")
    return verify_token(token)


async def get_cart_owner(
    authorization: str | None = Header(None, alias="Authorization"),
    x_guest_id: str | None = Header(None, alias="X-Guest-Id"),
) -> str:
    """Dueño del carrito: el `sub` del token o, para invitados, `guest:<uuid>`.

    El prefijo garantiza que un invitado nunca pueda apuntar al carrito de un usuario real.
    """
    token = _bearer(authorization)
    if token is not None:
        return verify_token(token).sub
    if x_guest_id:
        try:
            return f"{GUEST_PREFIX}{uuid.UUID(x_guest_id.strip())}"
        except ValueError:
            pass
    raise _unauthorized("Se requiere sesión o un identificador de invitado válido.")
