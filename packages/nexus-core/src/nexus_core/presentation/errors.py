"""Manejadores globales de excepciones fail-closed (OWASP A10).

El cliente recibe solo un mensaje controlado; la traza, el SQL y las rutas internas van únicamente al log
(y de ahí a Loki/Tempo, correlacionados por `trace_id` y `request_id`).
"""

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from nexus_core.domain.exceptions import (
    BusinessRuleViolationException,
    DomainException,
    ForbiddenException,
    ResourceNotFoundException,
    UnauthorizedException,
)
from nexus_core.presentation.request_id import REQUEST_ID_HEADER, get_request_id

logger = logging.getLogger("nexus.errors")

GENERIC_500 = "Error interno del servidor."

_DOMAIN_STATUS: list[tuple[type[DomainException], int]] = [
    (ResourceNotFoundException, status.HTTP_404_NOT_FOUND),
    (BusinessRuleViolationException, status.HTTP_409_CONFLICT),
    (UnauthorizedException, status.HTTP_401_UNAUTHORIZED),
    (ForbiddenException, status.HTTP_403_FORBIDDEN),
]


def _json(request: Request, status_code: int, content: dict, headers: dict[str, str] | None = None) -> JSONResponse:
    merged = {REQUEST_ID_HEADER: get_request_id(request), "Cache-Control": "no-store", **(headers or {})}
    return JSONResponse(status_code=status_code, content=content, headers=merged)


def _safe_validation_errors(errors: list[dict]) -> list[dict]:
    """Solo ubicación, mensaje y tipo: nunca `input` ni `ctx` (podrían contener contraseñas o PII)."""
    return [{"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))} for e in errors]


async def _domain_handler(request: Request, exc: DomainException) -> JSONResponse:
    for exc_type, code in _DOMAIN_STATUS:
        if isinstance(exc, exc_type):
            headers = {"WWW-Authenticate": "Bearer"} if code == status.HTTP_401_UNAUTHORIZED else None
            return _json(request, code, {"detail": exc.message}, headers)
    # Excepción de dominio sin mapeo explícito: regla de negocio genérica, sin detalles internos.
    logger.warning("Excepción de dominio sin mapeo: %s", type(exc).__name__)
    return _json(request, status.HTTP_400_BAD_REQUEST, {"detail": "Solicitud inválida."})


async def _http_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _json(request, exc.status_code, {"detail": exc.detail}, dict(exc.headers or {}))


async def _validation_handler(request: Request, exc: RequestValidationError | ValidationError) -> JSONResponse:
    return _json(request, 422, {"detail": _safe_validation_errors(exc.errors())})


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = get_request_id(request)
    logger.error(
        "Excepción no controlada en %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"request_id": request_id, "exception_type": type(exc).__name__},
    )
    # Este handler corre en ServerErrorMiddleware (fuera de los middlewares de usuario): añade las cabeceras
    # de seguridad aquí también.
    from nexus_core.presentation.security import SECURITY_HEADERS

    return _json(request, status.HTTP_500_INTERNAL_SERVER_ERROR, {"detail": GENERIC_500, "request_id": request_id}, SECURITY_HEADERS)


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainException, _domain_handler)
    app.add_exception_handler(HTTPException, _http_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(ValidationError, _validation_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
