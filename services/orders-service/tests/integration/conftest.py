import pytest
from sqlalchemy import text

from nexus_core.infrastructure.database import (
    Base,
    DatabaseConnectionConfig,
    create_db_engine,
    create_session_factory,
)
from nexus_events import outbox  # noqa: F401  registra outbox_events
from orders_service.infrastructure import models  # noqa: F401  registra orders/order_items


@pytest.fixture(scope="session")
async def orders_engine(postgres_url):
    engine = create_db_engine(DatabaseConnectionConfig(database_url=postgres_url))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(orders_engine):
    return create_session_factory(orders_engine)


@pytest.fixture(autouse=True)
async def _clean_orders_tables(orders_engine):
    yield
    async with orders_engine.begin() as conn:
        await conn.execute(text("TRUNCATE order_items, orders, outbox_events CASCADE"))
