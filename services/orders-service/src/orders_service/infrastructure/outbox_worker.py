import asyncio
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from nexus_events.outbox import OutboxEventModel
from nexus_events.publisher import EventPublisher

logger = logging.getLogger("orders.outbox_worker")


class OutboxWorker:
    """Worker en segundo plano que procesa eventos de la tabla Outbox y los publica en Amazon SNS."""

    def __init__(self, session_factory: async_sessionmaker, publisher: EventPublisher) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("Outbox worker started.")
        while self._running:
            try:
                async with self._session_factory() as session:
                    stmt = select(OutboxEventModel).where(OutboxEventModel.processed.is_(False)).limit(20)
                    result = await session.execute(stmt)
                    events = result.scalars().all()

                    for event in events:
                        # Publicar en el topic SNS de eventos; si falla, la fila queda pendiente
                        await self._publisher.publish_raw(event.event_type, event.payload_json)
                        event.processed = True
                        event.processed_at = datetime.now(timezone.utc)

                    if events:
                        await session.commit()
                        logger.info("Dispatched %d outbox events.", len(events))

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Outbox worker iteration error: %s", exc)

            await asyncio.sleep(2)

