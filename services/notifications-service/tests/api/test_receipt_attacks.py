"""Ataques contra /send-receipt llamado directamente (saltándose el BFF): phishing desde el correo oficial."""

import pytest

from nexus_testkit import auth_headers

URL = "/api/v1/notifications/send-receipt"
BASE = {"order_id": "3f6678d1-829b-494e-a94c-f49ff420ebad", "customer_email": "ana@b.cl", "total_amount_clp": 1000}


def _sent_html(smtp_send) -> str:
    return smtp_send.await_args.args[0].get_content()


async def test_client_supplied_html_body_is_ignored(client, smtp_send):
    payload = {**BASE, "html_content": "<h1>Tu cuenta fue suspendida</h1><a href='http://phish.example'>entra</a>"}
    assert (await client.post(URL, json=payload, headers=auth_headers(email="ana@b.cl"))).status_code == 200
    html = _sent_html(smtp_send)
    assert "phish.example" not in html and "Tu cuenta fue suspendida" not in html


async def test_client_supplied_subject_is_ignored(client, smtp_send):
    payload = {**BASE, "subject": "URGENTE: verifica tu tarjeta"}
    await client.post(URL, json=payload, headers=auth_headers(email="ana@b.cl"))
    assert "URGENTE" not in smtp_send.await_args.args[0]["Subject"]


@pytest.mark.parametrize("field", ["folio", "transaction_id"])
async def test_header_and_html_injection_via_receipt_fields_is_neutralized(client, smtp_send, field):
    payload = {**BASE, field: "X\r\nBcc: victim@evil.example<script>alert(1)</script>"}
    r = await client.post(URL, json=payload, headers=auth_headers(email="ana@b.cl"))
    if r.status_code == 200:
        msg = smtp_send.await_args.args[0]
        assert msg["Bcc"] is None
        assert "<script>" not in msg.get_content()
    else:
        assert r.status_code == 422


async def test_license_key_html_is_escaped(client, smtp_send):
    payload = {**BASE, "license_keys": [{"product_title": "<img src=x onerror=alert(1)>", "key": "<b>K</b>"}]}
    await client.post(URL, json=payload, headers=auth_headers(email="ana@b.cl"))
    html = _sent_html(smtp_send)
    assert "<img src=x" not in html and "<b>K</b>" not in html


@pytest.mark.parametrize(
    "payload",
    [
        {**BASE, "order_id": "../../admin"},
        {**BASE, "items": [{"title": "x", "quantity": 1}] * 51},
        {**BASE, "license_keys": [{"product_title": "x", "key": "k"}] * 51},
        {**BASE, "customer_name": "A" * 201},
    ],
)
async def test_oversized_or_malformed_receipts_are_rejected(client, smtp_send, payload):
    assert (await client.post(URL, json=payload, headers=auth_headers(email="ana@b.cl"))).status_code == 422
    smtp_send.assert_not_awaited()
