import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nexus_testkit import TEST_JWT_SECRET


async def test_postgres_container_answers(postgres_url):
    engine = create_async_engine(postgres_url)
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()


def test_make_token_roundtrip(make_token):
    claims = jwt.decode(make_token(), TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == "user-1"
    assert claims["role"] == "customer"
