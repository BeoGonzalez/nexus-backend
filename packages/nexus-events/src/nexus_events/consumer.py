"""Consumidor de eventos desde una cola Amazon SQS suscrita al topic SNS de eventos.

Garantias:
- Long polling (por defecto 20 s): pocas llamadas, bajo costo.
- El mensaje se borra SOLO si el handler termina sin error. Si falla (o el JSON es invalido), SQS lo
  vuelve a entregar tras el visibility timeout y, despues de N intentos, lo mueve a la DLQ.
- event_type: atributo de mensaje (entrega raw de SNS) o, si no viene, el campo "event_type" del JSON.
"""

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("nexus.events.consumer")

EventHandler = Callable[[str, dict], Awaitable[Any]]


class SqsEventConsumer:
    def __init__(
        self,
        queue_url: str | None,
        handler: EventHandler,
        region: str | None = None,
        sqs_client: Any | None = None,
        wait_seconds: int = 20,
        max_messages: int = 10,
    ) -> None:
        self._queue_url = (queue_url or "").strip()
        self._handler = handler
        self._region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        self._client = sqs_client
        self._wait_seconds = wait_seconds
        self._max_messages = max_messages
        self._running = False

    def _sqs(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("sqs", region_name=self._region)
        return self._client

    async def poll_once(self) -> int:
        """Recibe un lote, lo procesa y devuelve cuantos mensajes se procesaron (y borraron)."""
        response = await asyncio.to_thread(
            self._sqs().receive_message,
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=self._max_messages,
            WaitTimeSeconds=self._wait_seconds,
            MessageAttributeNames=["event_type"],
        )
        processed = 0
        for message in response.get("Messages", []):
            if await self._process(message):
                await asyncio.to_thread(
                    self._sqs().delete_message, QueueUrl=self._queue_url, ReceiptHandle=message["ReceiptHandle"]
                )
                processed += 1
        return processed

    async def _process(self, message: dict) -> bool:
        message_id = message.get("MessageId")
        try:
            payload = json.loads(message["Body"])
            if not isinstance(payload, dict):
                raise ValueError("el evento debe ser un objeto JSON")
            attribute = (message.get("MessageAttributes") or {}).get("event_type") or {}
            event_type = attribute.get("StringValue") or payload.get("event_type") or "unknown"
            logger.info("Evento recibido %s (%s)", event_type, message_id)
            await self._handler(event_type, payload)
            return True
        except Exception:
            logger.exception("No se pudo procesar el mensaje %s: se reintentara (DLQ tras N intentos)", message_id)
            return False

    async def start(self) -> None:
        if not self._queue_url:
            logger.warning("EVENTS_QUEUE_URL no configurada: consumidor de eventos desactivado")
            return
        self._running = True
        logger.info("Consumidor SQS escuchando %s", self._queue_url)
        while self._running:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Error leyendo SQS (%s); reintento en 5 s", exc)
                await asyncio.sleep(5)

    def stop(self) -> None:
        self._running = False
