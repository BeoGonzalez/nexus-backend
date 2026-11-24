import base64
import json
import logging

from nexus_core.infrastructure.logging import JSONFormatter, setup_service_logging


def _record(msg="hola %s", args=("mundo",), exc_info=None):
    return logging.LogRecord("svc", logging.WARNING, __file__, 10, msg, args, exc_info)


def test_formatter_emits_parseable_json_with_rendered_message():
    entry = json.loads(JSONFormatter().format(_record()))
    assert entry["message"] == "hola mundo"
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "svc"


def test_formatter_includes_traceback_when_exception_present():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        entry = json.loads(JSONFormatter().format(_record(exc_info=sys.exc_info())))
    assert "ValueError: boom" in entry["exception"]


def test_setup_twice_does_not_duplicate_handlers():
    setup_service_logging("svc-a")
    logger = setup_service_logging("svc-a")
    assert len(logger.handlers) == 1
    assert len(logging.getLogger().handlers) == 1


# --- A09: redacción de secretos/PII y correlación de trazas -------------------------------

import pytest

from nexus_core.infrastructure.logging import log_security_event, redact


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# JWT ficticio armado en tiempo de ejecución: no hay token literal en el repo (evita falsos positivos de escáneres).
_FAKE_JWT = ".".join((_b64(b'{"alg":"HS256"}'), _b64(b'{"sub":"1"}'), _b64(b"signature")))


@pytest.mark.parametrize(
    "raw, leaked",
    [
        ("Authorization: Bearer " + _FAKE_JWT, _FAKE_JWT.split(".")[0]),
        ("token=" + _FAKE_JWT, _FAKE_JWT.split(".")[2]),
        ('{"password": "Sup3rS3cret!"}', "Sup3rS3cret!"),
        ("password=hunter2&x=1", "hunter2"),
        ("api_key=gsk_abcdef123456", "gsk_abcdef123456"),  # gitleaks:allow (valor ficticio)
        ("client_secret: abc123def", "abc123def"),
        ("refresh_token=opaque-refresh-value", "opaque-refresh-value"),
    ],
)
def test_redact_removes_credentials(raw, leaked):
    assert leaked not in redact(raw)


def test_redact_masks_emails_but_keeps_domain():
    assert redact("login fallido para ana.perez@nexus.cl") == "login fallido para a***@nexus.cl"


def test_formatter_redacts_message_and_extra_fields():
    record = _record(msg="pwd=%s", args=("x",))
    record.password = "hunter2"
    record.user_email = "ana@nexus.cl"
    entry = json.loads(JSONFormatter().format(record))
    assert entry["password"] == "[REDACTED]"
    assert entry["user_email"] == "a***@nexus.cl"


def test_security_event_is_structured_and_redacted(capsys):
    setup_service_logging("svc-sec")
    log_security_event("auth.login_failed", email="ana@nexus.cl", token="abc", path="/api/v1/auth/login")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    entry = json.loads(line)
    assert entry["security_event"] == "auth.login_failed"
    assert entry["logger"] == "nexus.security"
    assert entry["email"] == "a***@nexus.cl"
    assert entry["token"] == "[REDACTED]"
    assert entry["path"] == "/api/v1/auth/login"


def test_formatter_includes_trace_and_span_ids_inside_a_span():
    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("op") as span:
        entry = json.loads(JSONFormatter().format(_record()))
        ctx = span.get_span_context()
    assert entry["trace_id"] == format(ctx.trace_id, "032x")
    assert entry["span_id"] == format(ctx.span_id, "016x")


def test_formatter_omits_trace_ids_without_span():
    entry = json.loads(JSONFormatter().format(_record()))
    assert "trace_id" not in entry
