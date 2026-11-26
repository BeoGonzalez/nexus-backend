"""Verificacion de JWT emitidos por un User Pool de Amazon Cognito (RS256 contra su JWKS)."""

from __future__ import annotations

from typing import Any

import jwt

from nexus_core.domain.exceptions import UnauthorizedException
from nexus_security.jwt import TokenPayload

ADMIN_GROUP = "admins"
_ACCEPTED_TOKEN_USES = {"id", "access"}


def is_placeholder_credential(value: str) -> bool:
    """Valores de ejemplo (.env.example, docs): `xxxx...` o `your-...` no son credenciales reales.

    Así, copiar `.env.example` a `.env` deja el sistema en modo local en vez de llamar a un
    User Pool inexistente (ResourceNotFoundException) y validar JWT locales como RS256.
    """
    lowered = (value or "").strip().lower()
    return lowered.startswith("your-") or "xxxx" in lowered


def cognito_settings_present(user_pool_id: str | None, client_id: str | None) -> bool:
    """True solo si ambos valores existen y ninguno es un placeholder."""
    pool = (user_pool_id or "").strip()
    client = (client_id or "").strip()
    return bool(pool and client) and not (is_placeholder_credential(pool) or is_placeholder_credential(client))


class CognitoJwtVerifier:
    """Valida firma (RS256 + JWKS del pool), emisor, expiracion, tipo de token y app client.

    - ID token: el app client va en `aud`.
    - Access token: el app client va en `client_id` (no trae `aud` ni `email`).
    El rol es `admin` si el usuario pertenece al grupo `admins`; si no, `customer`.
    """

    def __init__(self, region: str, user_pool_id: str, client_id: str, jwks_client: Any | None = None) -> None:
        self.issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}"
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self.client_id = client_id
        self._jwks = jwks_client or jwt.PyJWKClient(self.jwks_url, cache_keys=True, lifespan=3600)

    def verify(self, token: str) -> TokenPayload:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],  # nunca HS256: evita la confusion de algoritmos
                issuer=self.issuer,
                options={"require": ["exp", "iss", "sub", "token_use"], "verify_aud": False},
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedException("El token de acceso ha expirado.") from exc
        except (jwt.PyJWTError, ValueError) as exc:
            raise UnauthorizedException("Token de acceso inválido.") from exc

        token_use = claims.get("token_use")
        if token_use not in _ACCEPTED_TOKEN_USES:
            raise UnauthorizedException("Token de acceso inválido.")
        audience = claims.get("aud") if token_use == "id" else claims.get("client_id")
        if audience != self.client_id:
            raise UnauthorizedException("Token de acceso inválido.")

        groups = claims.get("cognito:groups") or []
        return TokenPayload(
            sub=claims["sub"],
            email=claims.get("email"),
            email_verified=claims.get("email_verified") in (True, "true"),
            role="admin" if ADMIN_GROUP in groups else "customer",
            exp=claims["exp"],
        )
