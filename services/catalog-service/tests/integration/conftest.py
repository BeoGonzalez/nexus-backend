import pytest
from sqlalchemy import text

from catalog_service.infrastructure import models  # noqa: F401  registra tablas en Base.metadata
from nexus_core.infrastructure.database import (
    Base,
    DatabaseConnectionConfig,
    create_db_engine,
    create_session_factory,
)


@pytest.fixture(scope="session")
async def catalog_engine(postgres_url):
    engine = create_db_engine(DatabaseConnectionConfig(database_url=postgres_url, pool_size=25))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(catalog_engine):
    return create_session_factory(catalog_engine)


@pytest.fixture(autouse=True)
async def _clean_catalog_tables(catalog_engine):
    yield
    async with catalog_engine.begin() as conn:
        await conn.execute(text("TRUNCATE product_genres, products, genres, platforms CASCADE"))
