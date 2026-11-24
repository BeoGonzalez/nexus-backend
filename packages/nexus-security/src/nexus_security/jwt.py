from datetime import datetime, timezone
from typing import Any
import jwt
from pydantic import BaseModel

from nexus_core.domain.exceptions import UnauthorizedException


class TokenPayload(BaseModel):
    sub: str
    email: str | None = None
    # Solo un email verificado prueba que el usuario controla esa casilla (Cognito permite
    # cambiar el atributo email sin verificarlo). Ausente = no verificado.
    email_verified: bool = False
    role: str = "customer"
    exp: int


def decode_access_token(token: str, secret_key: str, algorithm: str = "HS256") -> TokenPayload:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException("El token de acceso ha expirado.")
    except jwt.InvalidTokenError:
        raise UnauthorizedException("Token de acceso inválido.")

