from __future__ import annotations

import logging
import urllib.parse
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import DateTime, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger("nexus.core.database")


class Base(DeclarativeBase):
    """Declarative Base class for SQLAlchemy ORM models."""
    pass


class TimestampMixin:
    """Mixin reutilizable de auditoría con UUID v4 nativo y timestamps server-side."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


@dataclass(frozen=True, slots=True)
class DatabaseConnectionConfig:
    """Configuración inyectable para conexiones a PostgreSQL / Aurora."""

    database_url: str
    echo: bool = False
    ssl: bool = False
    pool_size: int = 10
    max_overflow: int = 5
    pool_recycle: int = 1800
    pool_pre_ping: bool = True

    @property
    def normalized_url(self) -> str:
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]

        parsed = urllib.parse.urlparse(url)
        if parsed.query:
            params_to_strip = {"sslmode", "channel_binding", "endpoint", "ssl"}
            query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            filtered_pairs = [pair for pair in query_pairs if pair[0].lower() not in params_to_strip]
            new_query = urllib.parse.urlencode(filtered_pairs)
            return urllib.parse.urlunparse(parsed._replace(query=new_query))
        return url

    @property
    def connect_args(self) -> dict[str, object]:
        args: dict[str, object] = {}
        if self.ssl:
            args["ssl"] = "require"
        return args


def create_db_engine(config: DatabaseConnectionConfig) -> AsyncEngine:
    return create_async_engine(
        config.normalized_url,
        echo=config.echo,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_recycle=config.pool_recycle,
        pool_pre_ping=config.pool_pre_ping,
        connect_args=config.connect_args,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

