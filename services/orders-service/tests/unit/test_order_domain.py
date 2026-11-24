import uuid

from hypothesis import given, strategies as st

from orders_service.domain.entities import Order, OrderItem


@given(st.lists(st.tuples(st.integers(1, 1_000_000), st.integers(1, 50)), max_size=10))
def test_total_is_sum_of_price_times_quantity(lines):
    order = Order(user_id="u", items=[OrderItem(uuid.uuid4(), q, p) for p, q in lines])
    order.calculate_total()
    assert order.total_amount_clp == sum(p * q for p, q in lines)


def test_concrete_total():
    order = Order(user_id="u", items=[OrderItem(uuid.uuid4(), 2, 19990), OrderItem(uuid.uuid4(), 1, 5000)])
    order.calculate_total()
    assert order.total_amount_clp == 44980
