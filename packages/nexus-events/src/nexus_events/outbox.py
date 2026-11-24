import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from nexus_core.infrastructure.database import Base, TimestampMixin


class OutboxEventModel(TimestampMixin, Base):
    """Tabla de Outbox Transaccional para garantizar publicación atómica de eventos en PostgreSQL."""
    __tablename__ = "outbox_events"

    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    processed: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

