"""Middleware HTTP de seguridad común a todos los microservicios (OWASP A06 / A09).

- Cabeceras: HSTS, CSP restrictiva (API JSON), nosniff, X-Frame-Options, Referrer-Policy, Cache-Control.
- CORS por allowlist explícita (`CORS_ALLOWED_ORIGINS`); `*` está prohibido (las rutas aceptan credenciales).
- TrustedHost opcional (`ALLOWED_HOSTS`); las rutas `/health` quedan exentas (las probes de kubelet llegan con la
  IP del pod como Host).
- `X-Request-ID` en cada respuesta y eventos de seguridad para 401/403/429.

Middlewares ASGI puros (sin BaseHTTPMiddleware) para no romper el streaming SSE del ai-agent.
"""

import os
from dataclasses import dataclass, field

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nexus_core.infrastructure.logging import log_security_event
from nexus_core.presentation.request_id import REQUEST_ID_HEADER, get_request_id

SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cache-Control": "no-store",
}
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_SECURITY_STATUS_EVENTS = {401: "http.unauthorized", 403: "http.forbidden", 429: "http.rate_limited"}
_CORS_HEADERS = ["Authorization", "Content-Type", "Accept", REQUEST_ID_HEADER, "X-Guest-Id"]


def _csv_env(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SecuritySettings:
    cors_allowed_origins: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=lambda: ["*"])
    enable_hsts: bool = True
    enable_api_docs: bool = False
    # A04/A06: tope de tamaño de cuerpo (DoS por memoria). Las APIs de Nexus intercambian JSON pequeños.
    max_body_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if "*" in self.cors_allowed_origins:
            raise ValueError("CORS_ALLOWED_ORIGINS no admite '*': declara los orígenes explícitamente.")

    @classmethod
    def from_env(cls) -> "SecuritySettings":
        return cls(
            cors_allowed_origins=_csv_env("CORS_ALLOWED_ORIGINS"),
            allowed_hosts=_csv_env("ALLOWED_HOSTS", "*"),
            enable_hsts=_bool_env("ENABLE_HSTS", True),
            enable_api_docs=_bool_env("ENABLE_API_DOCS", False),
            max_body_bytes=int(os.getenv("MAX_REQUEST_BODY_BYTES", "1048576")),
        )


class SecurityHeadersMiddleware:
    """Añade cabeceras de seguridad y X-Request-ID; registra eventos de seguridad por código de estado."""

    def __init__(self, app: ASGIApp, settings: SecuritySettings) -> None:
        self.app = app
        self.headers = {k: v for k, v in SECURITY_HEADERS.items() if settings.enable_hsts or k != "Strict-Transport-Security"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.requests import HTTPConnection

        conn = HTTPConnection(scope)
        request_id = get_request_id(conn)
        path = scope.get("path", "")
        relax_csp = path.endswith(_DOCS_PATHS)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.decode("latin-1").lower() for k, _ in message.get("headers", [])}
                extra = [(REQUEST_ID_HEADER, request_id)] + [
                    (k, v) for k, v in self.headers.items() if not (relax_csp and k == "Content-Security-Policy")
                ]
                message["headers"] = list(message.get("headers", [])) + [
                    (k.encode("latin-1"), v.encode("latin-1")) for k, v in extra if k.lower() not in existing
                ]
                event = _SECURITY_STATUS_EVENTS.get(message["status"])
                if event:
                    client = scope.get("client") or ("unknown", 0)
                    log_security_event(
                        event,
                        status_code=message["status"],
                        method=scope.get("method"),
                        path=path,
                        client_ip=client[0],
                        forwarded_for=conn.headers.get("x-forwarded-for", ""),
                        user_agent=conn.headers.get("user-agent", ""),
                        request_id=request_id,
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class TrustedHostMiddleware:
    """Rechaza Host no permitidos (400); `*` desactiva la comprobación; `*.dominio` acepta subdominios."""

    def __init__(self, app: ASGIApp, allowed_hosts: list[str]) -> None:
        self.app = app
        self.allowed = [h.lower() for h in allowed_hosts]
        self.allow_any = "*" in self.allowed

    def _is_allowed(self, host: str) -> bool:
        host = host.split(":", 1)[0].lower()
        for pattern in self.allowed:
            if pattern == host or (pattern.startswith("*.") and host.endswith(pattern[1:])):
                return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.allow_any or scope["type"] not in ("http", "websocket") or scope.get("path", "").endswith("/health"):
            await self.app(scope, receive, send)
            return
        host = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"host"), "")
        if self._is_allowed(host):
            await self.app(scope, receive, send)
            return
        log_security_event("http.invalid_host", host=host, path=scope.get("path", ""))
        await PlainTextResponse("Invalid host header", status_code=400)(scope, receive, send)


class BodySizeLimitMiddleware:
    """413 si el cuerpo supera el límite, declare o no Content-Length (también en transferencias por chunks)."""

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = next((v for k, v in scope.get("headers", []) if k == b"content-length"), None)
        if declared is not None and declared.isdigit() and int(declared) > self.max:
            await self._reject(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max:
                    from fastapi import HTTPException

                    raise HTTPException(status_code=413, detail="La solicitud excede el tamaño permitido.")
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except Exception as exc:  # el límite saltó fuera de una ruta FastAPI
            if getattr(exc, "status_code", None) == 413 and not started:
                await self._reject(scope, receive, send)
                return
            raise

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        log_security_event("http.body_too_large", path=scope.get("path", ""))
        from starlette.responses import JSONResponse

        await JSONResponse({"detail": "La solicitud excede el tamaño permitido."}, status_code=413)(scope, receive, send)


def install_security_middleware(app: FastAPI, settings: SecuritySettings | None = None) -> None:
    settings = settings or SecuritySettings.from_env()
    # add_middleware apila: el último añadido es el más externo. Orden efectivo:
    # SecurityHeaders -> TrustedHost -> CORS -> app
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=_CORS_HEADERS,
            expose_headers=[REQUEST_ID_HEADER],
            max_age=600,
        )
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)


def _disable_api_docs(app: FastAPI) -> None:
    paths = {app.openapi_url, app.docs_url, app.redoc_url, app.swagger_ui_oauth2_redirect_url}
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) not in paths]
    app.openapi_url = app.docs_url = app.redoc_url = None


def configure_service(app: FastAPI, service_name: str, settings: SecuritySettings | None = None) -> None:
    """Punto único de hardening de un microservicio: errores (A10), middleware (A06/A09) y telemetría (A09)."""
    from nexus_core.infrastructure.telemetry import setup_telemetry
    from nexus_core.presentation.errors import install_exception_handlers

    settings = settings or SecuritySettings.from_env()
    if not settings.enable_api_docs:
        _disable_api_docs(app)
    install_exception_handlers(app)
    install_security_middleware(app, settings)
    setup_telemetry(app, service_name)
