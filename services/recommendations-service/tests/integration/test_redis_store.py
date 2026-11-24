import json
import uuid

import pytest
import redis.asyncio as redis

from recommendations_service.infrastructure.redis_store import RedisRecommendationStore


def _items(*titles):
    return json.dumps([{"product_id": str(uuid.uuid4()), "title": t, "price_clp": 1000, "score": 0.5} for t in titles])


@pytest.fixture
async def r(redis_url):
    client = redis.from_url(redis_url, decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()


async def test_personal_recommendations_are_returned_and_limited(r):
    await r.set("recommendations:alice", _items("A", "B", "C"))
    recs = await RedisRecommendationStore(r).get_recommendations_for_user("alice", limit=2)
    assert [x.title for x in recs] == ["A", "B"]
    assert recs[0].recommendation_reason == "Basado en tus preferencias"


async def test_user_without_profile_falls_back_to_trending(r):
    await r.set("recommendations:trending", _items("T1", "T2"))
    recs = await RedisRecommendationStore(r).get_recommendations_for_user("nobody")
    assert [x.title for x in recs] == ["T1", "T2"]
    assert recs[0].recommendation_reason == "Más populares de la semana"


async def test_empty_redis_returns_bounded_synthetic_fallback(r):
    assert len(await RedisRecommendationStore(r).get_trending_products(limit=1)) == 1
    assert len(await RedisRecommendationStore(r).get_trending_products(limit=6)) == 2


async def test_interactions_accumulate_affinity_with_expiry(r):
    store, pid = RedisRecommendationStore(r), uuid.uuid4()
    await store.track_interaction("alice", pid, 1.5)
    await store.track_interaction("alice", pid, 2.0)
    assert await r.zscore("affinity:alice", str(pid)) == 3.5
    assert 0 < await r.ttl("affinity:alice") <= 60 * 60 * 24 * 30
