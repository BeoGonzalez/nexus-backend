from unittest.mock import AsyncMock

import httpx
import pytest

from notifications_service.domain.ports import EmailSenderPort


class FakeEmailSender(EmailSenderPort):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_email(self, recipient: str, subject: str, html_content: str) -> bool:
        self.sent.append((recipient, subject, html_content))
        return True


@pytest.fixture(autouse=True)
def smtp_send(monkeypatch):
    """Red de seguridad: ningún test de este servicio puede enviar correo real.

    El adaptador SMTP cae a credenciales embebidas cuando las variables están vacías,
    así que parcheamos el envío a nivel de módulo para TODOS los tests.
    """
    from notifications_service.infrastructure import email_adapter

    mock = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(email_adapter.aiosmtplib, "send", mock)
    return mock


@pytest.fixture
def sender():
    return FakeEmailSender()


@pytest.fixture
async def client():
    from notifications_service.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://notif") as c:
        yield c
