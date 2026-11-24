import pytest
from notifications_service.application.handlers import NotificationEventHandler
from notifications_service.domain.ports import EmailSenderPort


class MockEmailSender(EmailSenderPort):
    def __init__(self) -> None:
        self.sent_emails: list[dict] = []

    async def send_email(self, recipient: str, subject: str, html_content: str) -> bool:
        self.sent_emails.append({
            "recipient": recipient,
            "subject": subject,
            "html": html_content,
        })
        return True


@pytest.mark.asyncio
async def test_notifications_sends_email_for_cognito_buyer():
    sender = MockEmailSender()
    handler = NotificationEventHandler(sender)

    event_payload = {
        "order_id": "ord-777",
        "user_id": "cognito-usr-alpha",
        "user_email": "cognito_buyer@gmail.com",
        "payment_id": "pay-stripe-999",
        "amount_paid_clp": 59990,
    }

    success = await handler.handle_payment_succeeded(event_payload)
    assert success is True
    assert len(sender.sent_emails) == 1

    email = sender.sent_emails[0]
    assert email["recipient"] == "cognito_buyer@gmail.com"
    assert "Gracias por comprar en Nexus Digital Store" in email["subject"]
    assert "¡Gracias por comprar en Nexus Digital Store!" in email["html"]
    assert "ord-777" in email["html"]
    assert "pay-stripe-999" in email["html"]
    assert "59.990" in email["html"] or "59,990" in email["html"]


@pytest.mark.asyncio
async def test_notifications_sends_email_for_local_buyer():
    sender = MockEmailSender()
    handler = NotificationEventHandler(sender)

    event_payload = {
        "order_id": "ord-888",
        "user_id": "local-usr-beta",
        "user_email": "local_gamer@outlook.com",
        "payment_id": "pay-webpay-111",
        "amount_paid_clp": 25000,
    }

    success = await handler.handle_payment_succeeded(event_payload)
    assert success is True
    assert len(sender.sent_emails) == 1
    assert sender.sent_emails[0]["recipient"] == "local_gamer@outlook.com"


@pytest.mark.asyncio
async def test_notifications_sends_receipt_with_items_to_benja():
    sender = MockEmailSender()
    handler = NotificationEventHandler(sender)

    event_payload = {
        "order_id": "ord-benja-101",
        "user_id": "usr-benja-gamer",
        "user_email": "benjagonzalez230@gmail.com",
        "payment_id": "pay-transbank-4455",
        "amount_paid_clp": 86980,
        "items": [
            {
                "product_id": "prod-1",
                "product_title": "Marvel's Spider-Man 2",
                "quantity": 1,
                "unit_price_clp": 49990,
            },
            {
                "product_id": "prod-2",
                "product_title": "Cyberpunk 2077: Ultimate Edition",
                "quantity": 1,
                "unit_price_clp": 36990,
            },
        ],
    }

    success = await handler.handle_payment_succeeded(event_payload)
    assert success is True
    assert len(sender.sent_emails) == 1

    email = sender.sent_emails[0]
    assert email["recipient"] == "benjagonzalez230@gmail.com"
    assert "Gracias por comprar en Nexus Digital Store" in email["subject"]
    assert "¡Gracias por comprar en Nexus Digital Store!" in email["html"]
    assert "Marvel's Spider-Man 2" in email["html"]
    assert "Cyberpunk 2077: Ultimate Edition" in email["html"]
    assert "86.980" in email["html"] or "86,980" in email["html"]
    assert "ord-benja-101" in email["html"]


