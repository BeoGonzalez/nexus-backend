import pytest
from hypothesis import given, strategies as st

from nexus_events.schemas.catalog import StockReleasedEvent, StockReservationFailedEvent, StockReservedEvent
from nexus_events.schemas.orders import OrderCreatedEvent, PaymentFailedEvent, PaymentSucceededEvent
from nexus_events.schemas.users import UserRegisteredEvent

EVENTS = [
    StockReservedEvent, StockReservationFailedEvent, StockReleasedEvent,
    OrderCreatedEvent, PaymentSucceededEvent, PaymentFailedEvent, UserRegisteredEvent,
]


@pytest.mark.parametrize("event_cls", EVENTS, ids=lambda c: c.__name__)
@given(data=st.data())
def test_event_survives_json_wire_roundtrip(event_cls, data):
    event = data.draw(st.builds(event_cls))
    assert event_cls.model_validate_json(event.model_dump_json()) == event


def test_each_event_gets_a_unique_id_and_utc_timestamp():
    a = UserRegisteredEvent(user_id="u", email="a@b.cl")
    b = UserRegisteredEvent(user_id="u", email="a@b.cl")
    assert a.event_id != b.event_id
    assert a.occurred_at.utcoffset().total_seconds() == 0
