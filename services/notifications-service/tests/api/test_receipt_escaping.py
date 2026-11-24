import pytest

from nexus_testkit import auth_headers

URL = "/api/v1/notifications/send-receipt"
BASE_RECEIPT = {"order_id": "3f6678d1-829b-494e-a94c-f49ff420ebad", "customer_email": "ana@b.cl", "total_amount_clp": 1000}


async def test_receipt_customer_name_is_html_escaped(client, smtp_send):
    payload = {**BASE_RECEIPT, "customer_name": '<a href="http://phish.example">Reclama tu premio</a>'}
    assert (await client.post(URL, json=payload, headers=auth_headers(email="ana@b.cl"))).status_code == 200
    assert '<a href="http://phish.example">' not in smtp_send.await_args.args[0].get_content()


async def test_receipt_item_title_is_html_escaped(client, smtp_send):
    payload = {**BASE_RECEIPT, "items": [{"title": "<script>alert(1)</script>", "quantity": 1, "unit_price_clp": 1000}]}
    assert (await client.post(URL, json=payload, headers=auth_headers(email="ana@b.cl"))).status_code == 200
    assert "<script>" not in smtp_send.await_args.args[0].get_content()
