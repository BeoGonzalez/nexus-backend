"""EventPublisher sobre Amazon SNS (reemplaza al exchange topic de RabbitMQ)."""

import json

from nexus_events.publisher import EventPublisher
from nexus_events.schemas.users import UserRegisteredEvent


def _receive(sqs, url, n=10):
    return sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=n, MessageAttributeNames=["All"]).get("Messages", [])


async def test_published_event_reaches_subscribed_queue_as_json_with_event_type(aws_events):
    url = aws_events.queue("users", {"event_type": ["user.registered"]})
    event = UserRegisteredEvent(user_id="u1", email="a@b.cl", full_name="Ana")

    await EventPublisher(aws_events.topic_arn).publish("user.registered", event)

    [msg] = _receive(aws_events.sqs, url)
    assert UserRegisteredEvent.model_validate_json(msg["Body"]) == event
    assert msg["MessageAttributes"]["event_type"]["StringValue"] == "user.registered"


async def test_filter_policy_routes_only_matching_events(aws_events):
    orders = aws_events.queue("orders", {"event_type": [{"prefix": "order."}]})
    publisher = EventPublisher(aws_events.topic_arn)

    await publisher.publish("user.registered", UserRegisteredEvent(user_id="u1", email="a@b.cl"))
    await publisher.publish_raw("order.created", json.dumps({"order_id": "o-1"}))

    msgs = _receive(aws_events.sqs, orders)
    assert [m["MessageAttributes"]["event_type"]["StringValue"] for m in msgs] == ["order.created"]
    assert json.loads(msgs[0]["Body"]) == {"order_id": "o-1"}


async def test_without_topic_publish_is_a_noop():
    publisher = EventPublisher(None)
    await publisher.publish("user.registered", UserRegisteredEvent(user_id="u1", email="a@b.cl"))
    await publisher.publish_raw("order.created", "{}")


async def test_connect_and_close_are_safe_to_call_repeatedly(aws_events):
    publisher = EventPublisher(aws_events.topic_arn)
    await publisher.connect()
    await publisher.close()
    await publisher.close()
    url = aws_events.queue("all")
    await publisher.publish("user.registered", UserRegisteredEvent(user_id="u2", email="b@b.cl"))
    assert len(_receive(aws_events.sqs, url)) == 1
