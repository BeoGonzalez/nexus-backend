"""El presupuesto de tokens es GLOBAL entre réplicas: dos pods comparten los contadores de Redis."""

import pytest
from testcontainers.redis import RedisContainer

from ai_agent_service.security.governor import QuotaExceeded
from ai_agent_service.security.token_budget import RedisCounterStore, TokenBudget


@pytest.fixture(scope="module")
def redis_url():
    with RedisContainer("redis:7-alpine") as redis:
        yield f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0"


def pod(url):
    return TokenBudget(RedisCounterStore(url), user_tokens_per_day=1000, global_tokens_per_day=10_000,
                       global_tokens_per_minute=10**9, global_requests_per_day=100)


async def test_two_pods_share_the_same_user_budget(redis_url):
    pod_a, pod_b = pod(redis_url), pod(redis_url)
    await pod_a.record("usuario-compartido", 600)
    await pod_b.record("usuario-compartido", 400)
    with pytest.raises(QuotaExceeded) as exc:
        await pod_a.check("usuario-compartido")  # el pod A ve lo que consumió el usuario en el pod B
    assert exc.value.reason == "user_tokens"


async def test_counters_expire_on_their_own(redis_url):
    import redis.asyncio as redis

    b = pod(redis_url)
    await b.record("ttl-user", 10)
    client = redis.from_url(redis_url, decode_responses=True)
    keys = await client.keys("llm:tok:*ttl-user*")
    ttls = [await client.ttl(k) for k in keys]
    assert ttls and all(0 < t <= 90_000 for t in ttls)
    await client.aclose()
