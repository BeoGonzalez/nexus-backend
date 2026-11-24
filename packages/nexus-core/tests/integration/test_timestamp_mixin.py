import uuid

from sqlalchemy import MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nexus_core.infrastructure.database import (
    DatabaseConnectionConfig,
    TimestampMixin,
    create_db_engine,
    create_session_factory,
)


class _ProbeBase(DeclarativeBase):
    metadata = MetaData()


class _Probe(TimestampMixin, _ProbeBase):
    __tablename__ = "probe_timestamp_mixin"
    name: Mapped[str] = mapped_column(String(20))


async def test_rows_inserted_via_raw_sql_get_server_side_uuid_and_timestamps(postgres_url):
    from sqlalchemy import text

    engine = create_db_engine(DatabaseConnectionConfig(database_url=postgres_url))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_ProbeBase.metadata.create_all)
            row = (await conn.execute(text(
                "INSERT INTO probe_timestamp_mixin (name) VALUES ('raw') RETURNING id, created_at, updated_at"
            ))).one()
        assert isinstance(row.id, uuid.UUID)
        assert row.created_at.tzinfo is not None
        assert row.updated_at.tzinfo is not None
    finally:
        await engine.dispose()


async def test_orm_insert_assigns_uuid_and_tz_aware_timestamps(postgres_url):
    engine = create_db_engine(DatabaseConnectionConfig(database_url=postgres_url))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_ProbeBase.metadata.create_all)
        async with create_session_factory(engine)() as session:
            probe = _Probe(name="orm")
            session.add(probe)
            await session.commit()
            assert isinstance(probe.id, uuid.UUID)
            assert probe.created_at.tzinfo is not None
    finally:
        await engine.dispose()
