import uuid

from hypothesis import given, strategies as st

from cart_service.domain.entities import Cart, CartItem

_items = st.lists(
    st.tuples(st.integers(min_value=1, max_value=1_000_000), st.integers(min_value=1, max_value=99)),
    max_size=10,
)


def _cart(pairs) -> Cart:
    return Cart(user_id="u", items=[
        CartItem(product_id=uuid.uuid4(), title="g", unit_price_clp=p, quantity=q) for p, q in pairs
    ])


@given(_items)
def test_totals_are_sum_of_line_items(pairs):
    cart = _cart(pairs)
    assert cart.total_amount_clp == sum(p * q for p, q in pairs)
    assert cart.total_items_count == sum(q for _, q in pairs)


def test_concrete_cart_totals():
    cart = _cart([(19990, 2), (5000, 1)])
    assert (cart.total_amount_clp, cart.total_items_count) == (44980, 3)


def test_empty_cart_totals_are_zero():
    assert (Cart(user_id="u").total_amount_clp, Cart(user_id="u").total_items_count) == (0, 0)
