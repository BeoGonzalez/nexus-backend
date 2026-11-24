"""Publicador de eventos de dominio en Amazon SNS.

Reemplaza al exchange topic de RabbitMQ (no disponible en AWS Academy Learner Lab). El routing key
viaja como atributo `event_type`: cada consumidor tiene una cola SQS suscrita al topic con un
filtro por ese atributo (p. ej. notifications = order.* + user.registered).

Sin `topic_arn` (desarrollo local sin AWS) publicar es un no-op que solo deja un log.
"""

import asyncio
import logging
import os
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("nexus.events.publisher")


class EventPublisher:
    def __init__(self, topic_arn: str | None, region: str | None = None, sns_client: Any | None = None) -> None:
        self._topic_arn = (topic_arn or "").strip()
        self._region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        self._client = sns_client

    def _sns(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("sns", region_name=self._region)
        return self._client

    async def connect(self) -> None:
        """Compatibilidad con la API anterior: SNS no mantiene conexiones."""

    async def close(self) -> None:
        """Compatibilidad con la API anterior: nada que cerrar."""

    async def publish(self, routing_key: str, event: BaseModel, exchange_name: str = "nexus_events") -> None:
        await self.publish_raw(routing_key, event.model_dump_json())

    async def publish_raw(self, event_type: str, payload_json: str) -> None:
        if not self._topic_arn:
            logger.info("EVENTS_TOPIC_ARN no configurado: evento %s no publicado", event_type)
            return

        def _send():
            return self._sns().publish(
                TopicArn=self._topic_arn,
                Message=payload_json,
                MessageAttributes={"event_type": {"DataType": "String", "StringValue": event_type}},
            )

        response = await asyncio.to_thread(_send)
        logger.debug("Published %s to SNS (%s)", event_type, response.get("MessageId"))
