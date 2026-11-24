"""LLM06 Unbounded Consumption: presupuesto en TOKENS alineado con los límites reales del proveedor.

Las cuotas por mensaje no bastan: un mensaje puede costar 500 o 7.000 tokens. Groq (plan actual) limita a
8.000 tokens/minuto y 1.000 peticiones/día para toda la cuenta, así que el presupuesto es global y compartido.
"""

import pytest

from ai_agent_service.security.governor import QuotaExceeded
from ai_agent_service.security.token_budget import (
    MemoryCounterStore,
    ResilientCounterStore,
    TokenBudget,
    estimate_tokens,
)


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:  # 2027-01-15 08:00 UTC
        self.t = t

    def __call__(self) -> float:
        return self.t


def budget(clock=None, **overrides):
    limits = dict(user_tokens_per_day=1000, global_tokens_per_day=5000, global_tokens_per_minute=800,
                  global_requests_per_day=100)
    limits.update(overrides)
    clock = clock or Clock()
    return TokenBudget(MemoryCounterStore(clock=clock), clock=clock, **limits)


async def test_user_within_budget_is_allowed_and_usage_is_recorded():
    b = budget()
    await b.check("u1")
    await b.record("u1", 300)
    assert (await b.usage("u1"))["user_tokens_today"] == 300


async def test_user_over_daily_tokens_is_rejected_until_next_utc_day():
    clock = Clock()
    b = budget(clock, global_tokens_per_minute=10**9)
    await b.record("u1", 1000)
    with pytest.raises(QuotaExceeded) as exc:
        await b.check("u1")
    assert exc.value.reason == "user_tokens"
    assert 0 < exc.value.retry_after <= 86_400
    await b.check("u2")  # otro usuario no se ve afectado
    clock.t += 86_400
    await b.check("u1")  # nuevo día UTC


async def test_global_tokens_per_minute_protect_the_provider_rate_limit():
    clock = Clock()
    b = budget(clock)
    await b.record("u1", 500)
    await b.record("u2", 300)
    with pytest.raises(QuotaExceeded) as exc:
        await b.check("u3")
    assert exc.value.reason == "global_tokens_minute"
    assert 0 < exc.value.retry_after <= 60
    clock.t += 60
    await b.check("u3")


async def test_global_daily_tokens_are_a_hard_ceiling_for_everyone():
    b = budget(global_tokens_per_minute=10**9)
    for i in range(5):
        await b.record(f"u{i}", 1000)
    with pytest.raises(QuotaExceeded) as exc:
        await b.check("nuevo")
    assert exc.value.reason == "global_tokens_day"


async def test_global_requests_per_day_stay_below_provider_quota():
    b = budget(global_requests_per_day=3)
    for _ in range(3):
        await b.check("u1")
    with pytest.raises(QuotaExceeded) as exc:
        await b.check("u2")
    assert exc.value.reason == "global_requests_day"


async def test_negative_or_absurd_usage_cannot_refund_budget():
    b = budget()
    await b.record("u1", -5000)
    await b.record("u1", 0)
    assert (await b.usage("u1"))["user_tokens_today"] == 0


def test_estimate_tokens_is_conservative_for_spanish_text():
    # ~3 caracteres por token: sobreestima (o200k da ~4 en español), nunca subestima a cero.
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 3000) == 1000


class BrokenStore:
    async def incr(self, key, amount, ttl):
        raise ConnectionError("redis caído")

    async def get_many(self, keys):
        raise ConnectionError("redis caído")


async def test_when_redis_fails_the_budget_falls_back_to_local_limits_not_to_unlimited():
    clock = Clock()
    store = ResilientCounterStore(BrokenStore(), MemoryCounterStore(clock=clock))
    b = TokenBudget(store, clock=clock, user_tokens_per_day=1000, global_tokens_per_day=5000,
                    global_tokens_per_minute=10**9, global_requests_per_day=100)
    await b.record("u1", 1000)
    with pytest.raises(QuotaExceeded):
        await b.check("u1")
    assert store.degraded
