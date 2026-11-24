"""SqsEventConsumer: entrega (event_type, payload) al handler y borra el mensaje solo si se proceso."""

import json

from nexus_events.consumer import SqsEventConsumer


def _send(sqs, url, body, event_type=None):
    kwargs = {"QueueUrl": url, "MessageBody": body if isinstance(body, str) else json.dumps(body)}
    if event_type:
        kwargs["MessageAttributes"] = {"event_type": {"DataType": "String", "StringValue": event_type}}
    sqs.send_message(**kwargs)


def _remaining(sqs, url):
    attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])
    return int(attrs["Attributes"]["ApproximateNumberOfMessages"])


async def test_dispatches_event_type_and_payload_then_deletes(aws_events):
    url = aws_events.queue("q")
    _send(aws_events.sqs, url, {"order_id": "o-1"}, "order.created")
    seen = []

    async def handler(event_type, payload):
        seen.append((event_type, payload))

    processed = await SqsEventConsumer(url, handler, wait_seconds=0).poll_once()

    assert processed == 1
    assert seen == [("order.created", {"order_id": "o-1"})]
    assert _remaining(aws_events.sqs, url) == 0


async def test_event_type_falls_back_to_body_field(aws_events):
    url = aws_events.queue("q")
    _send(aws_events.sqs, url, {"event_type": "user.registered", "email": "a@b.cl"})
    seen = []

    async def handler(event_type, payload):
        seen.append(event_type)

    await SqsEventConsumer(url, handler, wait_seconds=0).poll_once()
    assert seen == ["user.registered"]


async def test_failed_handler_leaves_message_for_retry_and_dlq(aws_events):
    url = aws_events.queue("q")
    _send(aws_events.sqs, url, {"order_id": "o-1"}, "order.created")

    async def broken(event_type, payload):
        raise RuntimeError("SMTP caido")

    assert await SqsEventConsumer(url, broken, wait_seconds=0).poll_once() == 0
    assert _remaining(aws_events.sqs, url) == 1


async def test_malformed_json_is_not_dispatched_and_not_deleted(aws_events):
    url = aws_events.queue("q")
    _send(aws_events.sqs, url, "no-es-json", "order.created")
    calls = []

    async def handler(event_type, payload):
        calls.append(payload)

    assert await SqsEventConsumer(url, handler, wait_seconds=0).poll_once() == 0
    assert calls == []
    assert _remaining(aws_events.sqs, url) == 1


async def test_without_queue_url_start_returns_immediately():
    async def handler(event_type, payload):  # pragma: no cover - no se llama
        raise AssertionError

    await SqsEventConsumer("", handler).start()
