"""A07: limitador de intentos para endpoints de autenticación."""

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from nexus_security.rate_limit import SlidingWindowRateLimiter, client_ip, rate_limit


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_max_then_blocks_until_window_passes():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60, clock=clock)
    assert [limiter.hit("k") for _ in range(4)] == [True, True, True, False]
    clock.now += 61
    assert limiter.hit("k") is True


def test_keys_are_independent():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    assert limiter.hit("a") and limiter.hit("b")
    assert limiter.hit("a") is False


def test_retry_after_is_positive_when_blocked():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60, clock=clock)
    limiter.hit("k")
    clock.now += 10
    limiter.hit("k")
    assert limiter.retry_after("k") == 50


def test_memory_is_bounded():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60, max_keys=100)
    for i in range(1000):
        limiter.hit(f"k{i}")
    assert len(limiter) <= 100


class Body(BaseModel):
    email: str


email_limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
ip_limiter = SlidingWindowRateLimiter(max_requests=100, window_seconds=60)
app = FastAPI()


@app.post("/login", dependencies=[Depends(rate_limit("auth.login", per_email=email_limiter, per_ip=ip_limiter))])
async def login(body: Body) -> dict:
    return {"ok": True}


@pytest.fixture
async def client():
    email_limiter.reset()
    ip_limiter.reset()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_same_email_is_blocked_even_when_rotating_forwarded_for(client):
    codes = [
        (await client.post("/login", json={"email": "Ana@Nexus.cl"}, headers={"X-Forwarded-For": f"198.51.100.{i}"})).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]


async def test_429_has_retry_after(client):
    for _ in range(3):
        r = await client.post("/login", json={"email": "ana@nexus.cl"})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0


async def test_email_comparison_is_case_and_space_insensitive(client):
    await client.post("/login", json={"email": "ana@nexus.cl"})
    await client.post("/login", json={"email": " ANA@nexus.cl "})
    assert (await client.post("/login", json={"email": "ana@NEXUS.cl"})).status_code == 429


def test_client_ip_uses_the_hop_appended_by_the_trusted_proxy(monkeypatch):
    from starlette.requests import Request

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    scope = {"type": "http", "client": ("10.0.1.5", 1), "headers": [(b"x-forwarded-for", b"1.1.1.1, 203.0.113.9")]}
    assert client_ip(Request(scope)) == "203.0.113.9"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    assert client_ip(Request(scope)) == "10.0.1.5"
