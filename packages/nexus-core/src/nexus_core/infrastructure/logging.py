"""Logging JSON para Grafana Loki (OWASP A09).

- Una línea JSON por evento, con `trace_id`/`span_id` del span OpenTelemetry activo (correlación Loki <-> Tempo).
- Redacción de credenciales y enmascarado de emails en el mensaje y en los campos `extra`.
- `log_security_event()` para eventos de seguridad (logger `nexus.security`, campo `security_event`).
"""

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

REDACTED = "[REDACTED]"
SECURITY_LOGGER = "nexus.security"

# Campos cuyo valor nunca debe llegar a los logs, venga como `extra` o como clave=valor en el mensaje.
_SENSITIVE_KEYS = (
    "password", "passwd", "pwd", "secret", "client_secret", "token", "access_token", "id_token",
    "refresh_token", "api_key", "apikey", "authorization", "cookie", "set-cookie", "session", "private_key",
    "aws_secret_access_key", "aws_session_token", "confirmation_code",
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?P<key>[\"']?\b(?:" + "|".join(re.escape(k) for k in _SENSITIVE_KEYS) + r")\b[\"']?\s*[:=]\s*[\"']?)"
    r"(?P<value>[^\"'&,;\s}]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_EMAIL_RE = re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

# Atributos estándar de LogRecord: lo demás son campos `extra` del llamador.
_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


def redact(value: str) -> str:
    """Elimina tokens, contraseñas y secretos; enmascara emails (`a***@dominio`)."""
    value = _BEARER_RE.sub(lambda m: f"{m.group(1)} {REDACTED}", value)
    value = _JWT_RE.sub(REDACTED, value)
    value = _SENSITIVE_KEY_RE.sub(lambda m: f"{m.group('key')}{REDACTED}", value)
    return _EMAIL_RE.sub(r"\1***@\2", value)


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return any(s == k or k.endswith(f"_{s}") or k.startswith(f"{s}_") for s in _SENSITIVE_KEYS)


def _sanitize(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _sanitize(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(key, v) for v in value]
    return redact(str(value))


def _trace_context() -> dict[str, str]:
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - OpenTelemetry es dependencia de nexus-core
        return {}
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return {}
    return {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x")}


class JSONFormatter(logging.Formatter):
    """Formateador JSON (Loki/CloudWatch) con redacción y contexto de traza."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        log_entry.update(_trace_context())
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_") and key not in log_entry:
                log_entry[key] = _sanitize(key, value)
        if record.exc_info:
            log_entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(log_entry, default=str, ensure_ascii=False)


def setup_service_logging(service_name: str, level: int = logging.INFO) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    logger = logging.getLogger(service_name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False  # el root ya tiene el mismo handler: evita líneas duplicadas
    return logger


def log_security_event(event: str, *, level: int = logging.WARNING, **fields: Any) -> None:
    """Registra un evento de seguridad (login fallido, 401/403, rate limit, cambio de permisos)."""
    extra = {k: v for k, v in fields.items() if k not in _RESERVED}
    extra["security_event"] = event
    logging.getLogger(SECURITY_LOGGER).log(level, "security_event %s", event, extra=extra)
