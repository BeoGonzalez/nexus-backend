"""LLM06 Unbounded Consumption: cuotas por usuario, concurrencia, tope global y circuit breaker."""

import pytest

from ai_agent_service.security.governor import QuotaExceeded, UsageGovernor


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def gov(**kw) -> tuple[UsageGovernor, Clock]:
    clock = Clock()
    defaults = dict(per_minute=3, per_day=5, max_concurrent=1, global_per_day=100, clock=clock)
    defaults.update(kw)
    return UsageGovernor(**defaults), clock


def test_per_minute_quota_then_recovers():
    g, clock = gov()
    for _ in range(3):
        g.acquire("ana").release()
    with pytest.raises(QuotaExceeded) as exc:
        g.acquire("ana")
    assert exc.value.reason == "per_minute" and exc.value.retry_after > 0
    clock.now += 61
    g.acquire("ana").release()


def test_daily_quota_is_enforced():
    g, clock = gov(per_minute=100)
    for _ in range(5):
        g.acquire("ana").release()
    with pytest.raises(QuotaExceeded) as exc:
        g.acquire("ana")
    assert exc.value.reason == "per_day"


def test_users_have_independent_quotas():
    g, _ = gov()
    for _ in range(3):
        g.acquire("ana").release()
    g.acquire("bob").release()


def test_concurrent_streams_per_user_are_limited_until_release():
    g, _ = gov(per_minute=10)
    lease = g.acquire("ana")
    with pytest.raises(QuotaExceeded) as exc:
        g.acquire("ana")
    assert exc.value.reason == "concurrency"
    lease.release()
    g.acquire("ana").release()


def test_release_is_idempotent():
    g, _ = gov(per_minute=10)
    lease = g.acquire("ana")
    lease.release()
    lease.release()
    g.acquire("ana").release()


def test_global_daily_cap_protects_the_budget():
    g, _ = gov(per_minute=100, per_day=100, global_per_day=4)
    for user in ("a", "b", "c", "d"):
        g.acquire(user).release()
    with pytest.raises(QuotaExceeded) as exc:
        g.acquire("e")
    assert exc.value.reason == "global_budget"


def test_rejected_requests_do_not_consume_quota():
    g, _ = gov(per_minute=10)
    lease = g.acquire("ana")
    for _ in range(5):
        with pytest.raises(QuotaExceeded):
            g.acquire("ana")
    lease.release()
    assert g.usage("ana")["day"] == 1


def test_disabled_governor_acts_as_kill_switch():
    g, _ = gov(enabled=False)
    with pytest.raises(QuotaExceeded) as exc:
        g.acquire("ana")
    assert exc.value.reason == "disabled"
