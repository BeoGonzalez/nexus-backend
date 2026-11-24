import pytest

from nexus_testkit import auth_headers

BASE = "/api/v1/notifications"
RECEIPT = {
    "order_id": "3f6678d1-829b-494e-a94c-f49ff420ebad",
    "customer_email": "ana@b.cl",
    "customer_name": "Ana",
    "total_amount_clp": 11900,
    "items": [{"title": "Hades II", "quantity": 1, "unit_price_clp": 11900}],
    "license_keys": [{"product_title": "Hades II", "key": "AAAA-BBBB"}],
}
OWNER = auth_headers(email="ana@b.cl")


@pytest.fixture(autouse=True)
def configured_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "store@test.cl")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pass")
    from notifications_service.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_app_imports_without_network():
    from notifications_service.main import app

    assert f"{BASE}/send-receipt" in app.openapi()["paths"]


async def test_receipt_is_emailed_to_customer_with_keys_and_iva(client, smtp_send):
    r = await client.post(f"{BASE}/send-receipt", json=RECEIPT, headers=OWNER)
    assert r.status_code == 200
    message = smtp_send.await_args.args[0]
    assert message["To"] == "ana@b.cl"
    html = message.get_content()
    assert "AAAA-BBBB" in html
    assert "Ana" in html


async def test_receipt_without_recipient_is_400(client, smtp_send):
    r = await client.post(f"{BASE}/send-receipt", json={**RECEIPT, "customer_email": "  "}, headers=OWNER)
    assert r.status_code == 400
    smtp_send.assert_not_awaited()


async def test_smtp_failure_is_reported_as_500(client, smtp_send):
    smtp_send.side_effect = OSError("down")
    r = await client.post(f"{BASE}/send-receipt", json=RECEIPT, headers=OWNER)
    assert r.status_code == 500


async def test_generic_email_is_sent(client, smtp_send):
    r = await client.post(f"{BASE}/email", json={"recipient": "a@b.cl", "subject": "s", "body_html": "<b>x</b>"},
                          headers=auth_headers(role="admin"))
    assert r.status_code == 200
    assert smtp_send.await_args.args[0]["To"] == "a@b.cl"


async def test_generic_email_requires_authentication(client, smtp_send):
    r = await client.post(f"{BASE}/email", json={"recipient": "victim@b.cl", "subject": "Urgente", "body_html": "<a>phish</a>"})
    assert r.status_code == 401
    smtp_send.assert_not_awaited()


async def test_send_receipt_requires_authentication(client, smtp_send):
    r = await client.post(f"{BASE}/send-receipt", json={**RECEIPT, "html_content": "<a>phish</a>"})
    assert r.status_code == 401
    smtp_send.assert_not_awaited()


async def test_health(client):
    assert (await client.get(f"{BASE}/health")).json()["status"] == "healthy"


async def test_receipt_to_someone_else_is_forbidden(client, smtp_send):
    r = await client.post(f"{BASE}/send-receipt", json={**RECEIPT, "customer_email": "victim@x.cl"}, headers=OWNER)
    assert r.status_code == 403
    smtp_send.assert_not_awaited()


async def test_receipt_with_token_without_email_is_forbidden(client, smtp_send):
    r = await client.post(f"{BASE}/send-receipt", json=RECEIPT, headers=auth_headers(email=None))
    assert r.status_code == 403
    smtp_send.assert_not_awaited()


async def test_receipt_email_match_is_case_insensitive(client, smtp_send):
    r = await client.post(f"{BASE}/send-receipt", json={**RECEIPT, "customer_email": "ANA@B.CL"}, headers=OWNER)
    assert r.status_code == 200
    assert smtp_send.await_args.args[0]["To"] == "ana@b.cl"


async def test_receipt_with_unverified_email_is_forbidden(client, smtp_send):
    """Cognito deja cambiar el atributo email sin verificarlo: sin email_verified sería un relay."""
    r = await client.post(f"{BASE}/send-receipt", json=RECEIPT,
                          headers=auth_headers(email="ana@b.cl", email_verified=False))
    assert r.status_code == 403
    smtp_send.assert_not_awaited()
