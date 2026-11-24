import pytest

from notifications_service.application.handlers import NotificationEventHandler

ORDER_ID = "3f6678d1-829b-494e-a94c-f49ff420ebad"


async def test_order_created_goes_to_buyer_email(sender):
    await NotificationEventHandler(sender).handle_order_created(
        {"order_id": ORDER_ID, "user_id": "u1", "user_email": "ana@b.cl", "total_amount_clp": 39980}
    )
    [(to, subject, body)] = sender.sent
    assert to == "ana@b.cl"
    assert "#3f6678d1" in subject
    assert "$39,980 CLP" in body


async def test_order_created_without_email_falls_back_to_user_alias(sender):
    await NotificationEventHandler(sender).handle_order_created({"order_id": ORDER_ID, "user_id": "u1"})
    assert sender.sent[0][0] == "u1@nexus-store.cl"


async def test_payment_receipt_lists_each_item_with_subtotal(sender):
    await NotificationEventHandler(sender).handle_payment_succeeded({
        "order_id": ORDER_ID, "user_id": "u1", "user_email": "ana@b.cl", "payment_id": "pay-777",
        "amount_paid_clp": 44980,
        "items": [
            {"product_title": "Hades II", "quantity": 2, "unit_price_clp": 19990},
            {"product_title": "Celeste", "quantity": 1, "unit_price_clp": 5000},
        ],
    })
    [(to, _, body)] = sender.sent
    assert to == "ana@b.cl"
    assert "pay-777" in body
    assert "Hades II" in body and "$39,980 CLP" in body
    assert "Celeste" in body
    assert "$44,980 CLP" in body


async def test_payment_receipt_without_items_shows_single_generic_line(sender):
    await NotificationEventHandler(sender).handle_payment_succeeded(
        {"order_id": ORDER_ID, "user_email": "ana@b.cl", "amount_paid_clp": 1000}
    )
    assert "Orden de Compra Digital Nexus" in sender.sent[0][2]


async def test_welcome_email_greets_by_name_or_default(sender):
    handler = NotificationEventHandler(sender)
    await handler.handle_user_registered({"email": "ana@b.cl", "full_name": "Ana"})
    await handler.handle_user_registered({"email": "bob@b.cl"})
    assert [(to, "Ana" in body, "Gamer" in body) for to, _, body in sender.sent] == [
        ("ana@b.cl", True, False), ("bob@b.cl", False, True)]


async def test_product_title_is_html_escaped(sender):
    await NotificationEventHandler(sender).handle_payment_succeeded({
        "order_id": ORDER_ID, "user_email": "ana@b.cl", "amount_paid_clp": 1,
        "items": [{"product_title": "<script>alert(1)</script>", "quantity": 1, "unit_price_clp": 1}],
    })
    assert "<script>" not in sender.sent[0][2]


async def test_user_name_is_html_escaped(sender):
    await NotificationEventHandler(sender).handle_user_registered(
        {"email": "a@b.cl", "full_name": '<a href="http://phish.example">Verifica tu cuenta</a>'}
    )
    assert '<a href="http://phish.example">' not in sender.sent[0][2]
