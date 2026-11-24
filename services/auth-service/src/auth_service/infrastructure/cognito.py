import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from auth_service.config import get_settings
from auth_service.domain.ports import IdentityProviderPort
from nexus_core.domain.exceptions import BusinessRuleViolationException, UnauthorizedException

logger = logging.getLogger("auth.cognito")

INVALID_CREDENTIALS = "Correo electrónico o contraseña incorrectos."


_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash scrypt con salt aleatorio: formato `scrypt$<salt_hex>$<hash_hex>`."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, _ = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _hash_password(password, bytes.fromhex(salt_hex))
    except ValueError:
        return False
    return hmac.compare_digest(expected, stored)


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def calculate_secret_hash(username: str, client_id: str, client_secret: str) -> str:
    """Calcula el HMAC-SHA256 SecretHash requerido por Cognito cuando el App Client tiene Secret."""
    message = bytes(username + client_id, "utf-8")
    key = bytes(client_secret, "utf-8")
    return base64.b64encode(hmac.new(key, message, digestmod=hashlib.sha256).digest()).decode()


class CognitoAdapter(IdentityProviderPort):
    def __init__(self) -> None:
        self.settings = get_settings()
        self._local_users: dict[str, dict[str, Any]] = {}
        # refresh token opaco -> email normalizado. Un solo uso: se rota en cada refresh.
        self._local_refresh_tokens: dict[str, str] = {}

    @property
    def is_configured(self) -> bool:
        pool_id = (self.settings.COGNITO_USER_POOL_ID or "").strip()
        client_id = (self.settings.COGNITO_APP_CLIENT_ID or "").strip()
        return bool(pool_id and client_id and pool_id != "your-user-pool-id")

    @property
    def local_mode_enabled(self) -> bool:
        return bool(self.settings.AUTH_LOCAL_MODE)

    def _ensure_local_mode(self) -> None:
        """Sin Cognito, solo se permite el modo local si esta activado explicitamente (fail-closed)."""
        if not self.local_mode_enabled:
            logger.error("Cognito no configurado y AUTH_LOCAL_MODE desactivado: login rechazado.")
            raise UnauthorizedException("Autenticación no configurada.")
        if not (self.settings.JWT_SECRET or "").strip():
            logger.error("AUTH_LOCAL_MODE activo sin JWT_SECRET: no se emiten tokens.")
            raise UnauthorizedException("Autenticación no configurada.")

    def _get_client(self):
        import boto3
        return boto3.client("cognito-idp", region_name=self.settings.COGNITO_REGION)

    def _secret_hash(self, username: str) -> str | None:
        if self.settings.COGNITO_APP_CLIENT_SECRET:
            return calculate_secret_hash(
                username=username,
                client_id=self.settings.COGNITO_APP_CLIENT_ID,
                client_secret=self.settings.COGNITO_APP_CLIENT_SECRET,
            )
        return None

    # =========================================================================
    # 1. INICIAR SESIÓN (InitiateAuth - USER_PASSWORD_AUTH)
    # =========================================================================
    async def authenticate(self, email: str, password: str) -> dict[str, Any]:
        if not self.is_configured:
            self._ensure_local_mode()
            return await self._local_authenticate(email, password)

        client = self._get_client()
        auth_params = {
            "USERNAME": email,
            "PASSWORD": password,
        }
        secret_hash = self._secret_hash(email)
        if secret_hash:
            auth_params["SECRET_HASH"] = secret_hash

        def _call_cognito():
            try:
                return client.initiate_auth(
                    AuthFlow="USER_PASSWORD_AUTH",
                    AuthParameters=auth_params,
                    ClientId=self.settings.COGNITO_APP_CLIENT_ID,
                )
            except client.exceptions.NotAuthorizedException:
                raise UnauthorizedException(INVALID_CREDENTIALS)
            except client.exceptions.UserNotFoundException:
                raise UnauthorizedException(INVALID_CREDENTIALS)
            except client.exceptions.UserNotConfirmedException:
                raise UnauthorizedException("Cuenta no confirmada. Por favor verifica tu código de correo.")
            except client.exceptions.PasswordResetRequiredException:
                raise UnauthorizedException("Se requiere cambio de contraseña.")
            except Exception as exc:
                logger.error("Error inesperado en Cognito initiate_auth: %s", exc)
                raise UnauthorizedException("El servicio de autenticación no está disponible. Inténtalo más tarde.")

        response = await asyncio.to_thread(_call_cognito)
        result = response.get("AuthenticationResult", {})
        return {
            "access_token": result.get("AccessToken", ""),
            "id_token": result.get("IdToken", ""),
            "refresh_token": result.get("RefreshToken"),
            "token_type": result.get("TokenType", "Bearer"),
            "expires_in": result.get("ExpiresIn", 3600),
        }

    # =========================================================================
    # 2. REGISTRO DE USUARIOS (SignUp)
    # =========================================================================
    async def register(self, email: str, password: str, name: str) -> dict[str, Any]:
        if not self.is_configured:
            self._ensure_local_mode()
            return await self._local_register(email, password, name)

        client = self._get_client()
        kwargs: dict[str, Any] = {
            "ClientId": self.settings.COGNITO_APP_CLIENT_ID,
            "Username": email,
            "Password": password,
            "UserAttributes": [
                {"Name": "email", "Value": email},
                {"Name": "name", "Value": name},
            ],
        }
        secret_hash = self._secret_hash(email)
        if secret_hash:
            kwargs["SecretHash"] = secret_hash

        def _call_signup():
            try:
                return client.sign_up(**kwargs)
            except client.exceptions.UsernameExistsException:
                raise BusinessRuleViolationException("Ya existe una cuenta con este correo electrónico.")
            except client.exceptions.InvalidPasswordException as exc:
                raise BusinessRuleViolationException("La contraseña no cumple la política: mínimo 8 caracteres con mayúsculas, minúsculas, números y símbolos.")
            except Exception as exc:
                logger.error("Error en Cognito sign_up: %s", exc)
                raise BusinessRuleViolationException("No fue posible registrar la cuenta. Inténtalo más tarde.")

        response = await asyncio.to_thread(_call_signup)
        return {
            "user_sub": response.get("UserSub", ""),
            "user_confirmed": response.get("UserConfirmed", False),
        }

    # =========================================================================
    # 3. CONFIRMACIÓN DE CUENTA (ConfirmSignUp)
    # =========================================================================
    async def confirm_signup(self, email: str, code: str) -> bool:
        if not self.is_configured:
            return True

        client = self._get_client()
        kwargs: dict[str, Any] = {
            "ClientId": self.settings.COGNITO_APP_CLIENT_ID,
            "Username": email,
            "ConfirmationCode": code,
        }
        secret_hash = self._secret_hash(email)
        if secret_hash:
            kwargs["SecretHash"] = secret_hash

        def _call_confirm():
            try:
                client.confirm_sign_up(**kwargs)
                return True
            except client.exceptions.CodeMismatchException:
                raise BusinessRuleViolationException("El código de verificación ingresado es incorrecto.")
            except client.exceptions.ExpiredCodeException:
                raise BusinessRuleViolationException("El código de verificación ha expirado.")
            except Exception as exc:
                logger.error("Error en confirm_sign_up: %s", exc)
                raise BusinessRuleViolationException("No fue posible confirmar la cuenta.")

        return await asyncio.to_thread(_call_confirm)

    # =========================================================================
    # 4. REENVIAR CÓDIGO (ResendConfirmationCode)
    # =========================================================================
    async def resend_confirmation_code(self, email: str) -> bool:
        if not self.is_configured:
            return True

        client = self._get_client()
        kwargs: dict[str, Any] = {
            "ClientId": self.settings.COGNITO_APP_CLIENT_ID,
            "Username": email,
        }
        secret_hash = self._secret_hash(email)
        if secret_hash:
            kwargs["SecretHash"] = secret_hash

        def _call_resend():
            try:
                client.resend_confirmation_code(**kwargs)
                return True
            except Exception as exc:
                logger.error("Error en resend_confirmation_code: %s", exc)
                raise BusinessRuleViolationException("No fue posible reenviar el código. Inténtalo más tarde.")

        return await asyncio.to_thread(_call_resend)

    # =========================================================================
    # 5. RENOVAR TOKEN (REFRESH_TOKEN_AUTH)
    # =========================================================================
    async def refresh_tokens(self, refresh_token: str, email: str | None = None) -> dict[str, Any]:
        if not self.is_configured:
            self._ensure_local_mode()
            return await self._local_refresh(refresh_token)

        client = self._get_client()
        auth_params = {"REFRESH_TOKEN": refresh_token}
        if email:
            secret_hash = self._secret_hash(email)
            if secret_hash:
                auth_params["SECRET_HASH"] = secret_hash

        def _call_refresh():
            try:
                return client.initiate_auth(
                    AuthFlow="REFRESH_TOKEN_AUTH",
                    AuthParameters=auth_params,
                    ClientId=self.settings.COGNITO_APP_CLIENT_ID,
                )
            except Exception as exc:
                logger.error("Error en REFRESH_TOKEN_AUTH: %s", exc)
                raise UnauthorizedException("El token de actualización ha expirado o es inválido.")

        response = await asyncio.to_thread(_call_refresh)
        result = response.get("AuthenticationResult", {})
        return {
            "access_token": result.get("AccessToken", ""),
            "id_token": result.get("IdToken", ""),
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": result.get("ExpiresIn", 3600),
        }

    # =========================================================================
    # 6. RECUPERACIÓN DE CONTRASEÑA (ForgotPassword & Confirm)
    # =========================================================================
    async def forgot_password(self, email: str) -> bool:
        if not self.is_configured:
            return True

        client = self._get_client()
        kwargs: dict[str, Any] = {
            "ClientId": self.settings.COGNITO_APP_CLIENT_ID,
            "Username": email,
        }
        secret_hash = self._secret_hash(email)
        if secret_hash:
            kwargs["SecretHash"] = secret_hash

        def _call_forgot():
            try:
                client.forgot_password(**kwargs)
                return True
            except Exception as exc:
                logger.error("Error en forgot_password: %s", exc)
                raise BusinessRuleViolationException("No fue posible iniciar la recuperación. Inténtalo más tarde.")

        return await asyncio.to_thread(_call_forgot)

    async def confirm_forgot_password(self, email: str, code: str, new_password: str) -> bool:
        if not self.is_configured:
            return True

        client = self._get_client()
        kwargs: dict[str, Any] = {
            "ClientId": self.settings.COGNITO_APP_CLIENT_ID,
            "Username": email,
            "ConfirmationCode": code,
            "Password": new_password,
        }
        secret_hash = self._secret_hash(email)
        if secret_hash:
            kwargs["SecretHash"] = secret_hash

        def _call_confirm_forgot():
            try:
                client.confirm_forgot_password(**kwargs)
                return True
            except Exception as exc:
                logger.error("Error en confirm_forgot_password: %s", exc)
                raise BusinessRuleViolationException("No fue posible restablecer la contraseña.")

        return await asyncio.to_thread(_call_confirm_forgot)

    async def get_user_from_token(self, token: str) -> dict[str, Any]:
        import jwt
        # Decodificación de claims sin validar firma si viene validado por Gateway
        decoded = jwt.decode(token, options={"verify_signature": False})
        return {
            "sub": decoded.get("sub", ""),
            "email": decoded.get("email", ""),
            "name": decoded.get("name", "Gamer"),
            "role": "admin" if "admin" in decoded.get("cognito:groups", []) else "customer",
        }

    # =========================================================================
    # FALLBACK LOCAL DETERMINISTA PARA TESTING & DESARROLLO SIN AWS COGNITO
    # =========================================================================
    def _local_role(self, email: str) -> str:
        admins = {_normalize_email(e) for e in self.settings.LOCAL_ADMIN_EMAILS.split(",") if e.strip()}
        return "admin" if email in admins else "customer"

    def _issue_local_tokens(self, email: str) -> dict[str, Any]:
        import jwt

        user = self._local_users[email]
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user["sub"],
            "email": email,
            # En modo local el email no se verifica por correo; el usuario lo fijó al registrarse.
            "email_verified": True,
            "name": user["name"],
            "role": self._local_role(email),
            "iss": "nexus-local-auth",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=2)).timestamp()),
        }
        token = jwt.encode(payload, self.settings.JWT_SECRET, algorithm=self.settings.JWT_ALGORITHM)
        refresh_token = secrets.token_urlsafe(32)
        self._local_refresh_tokens[refresh_token] = email
        return {
            "access_token": token,
            "id_token": token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": 7200,
        }

    async def _local_authenticate(self, email: str, password: str) -> dict[str, Any]:
        email = _normalize_email(email)
        user = self._local_users.get(email)
        if user is None or not _verify_password(password, user["password_hash"]):
            raise UnauthorizedException("Credenciales inválidas.")
        return self._issue_local_tokens(email)

    async def _local_register(self, email: str, password: str, name: str) -> dict[str, Any]:
        email = _normalize_email(email)
        if email in self._local_users:
            raise BusinessRuleViolationException("Ya existe una cuenta con ese correo.")
        sub = f"usr-local-{secrets.token_hex(8)}"
        self._local_users[email] = {
            "sub": sub,
            "name": name,
            "password_hash": _hash_password(password),
        }
        return {"user_sub": sub, "user_confirmed": True}

    async def _local_refresh(self, refresh_token: str) -> dict[str, Any]:
        email = self._local_refresh_tokens.pop(refresh_token or "", None)
        if email is None or email not in self._local_users:
            raise UnauthorizedException("Refresh token inválido o expirado.")
        return self._issue_local_tokens(email)
