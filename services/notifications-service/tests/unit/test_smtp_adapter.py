import pytest

from notifications_service.config import Settings
from notifications_service.infrastructure.email_adapter import SmtpEmailAdapter


def _adapter(user: str, password: str) -> SmtpEmailAdapter:
    adapter = SmtpEmailAdapter()
    adapter._settings = Settings(SMTP_USER=user, SMTP_PASSWORD=password, SMTP_HOST="smtp.test", SMTP_PORT=2525)
    return adapter


async def test_sends_html_message_over_starttls_with_configured_credentials(smtp_send):
    assert await _adapter("store@test.cl", "app-pass").send_email("ana@b.cl", "Hola", "<p>hi</p>") is True
    smtp_send.assert_awaited_once()
    message = smtp_send.await_args.args[0]
    kwargs = smtp_send.await_args.kwargs
    assert (message["To"], message["Subject"]) == ("ana@b.cl", "Hola")
    assert message.get_content_type() == "text/html"
    assert (kwargs["hostname"], kwargs["port"], kwargs["username"], kwargs["start_tls"]) == (
        "smtp.test", 2525, "store@test.cl", True)


async def test_smtp_failure_returns_false(smtp_send):
    smtp_send.side_effect = OSError("connection refused")
    assert await _adapter("store@test.cl", "app-pass").send_email("ana@b.cl", "Hola", "x") is False


async def test_without_credentials_does_not_send_with_embedded_account(smtp_send):
    assert await _adapter("", "").send_email("ana@b.cl", "Hola", "x") is True
    smtp_send.assert_not_awaited()
