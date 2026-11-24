"""Presupuesto de tokens del LLM (OWASP LLM06 Unbounded Consumption / denial of wallet).

Complementa al UsageGovernor (peticiones y concurrencia por usuario, en memoria del pod) con límites en TOKENS,
que es lo que factura y limita el proveedor. Los contadores viven en Redis para que sean GLOBALES entre pods:

    llm:tok:user:<sub>:<AAAAMMDD>     tokens del usuario en el día UTC
    llm:tok:global:<AAAAMMDD>         tokens de todo el sitio en el día UTC
    llm:tok:global:min:<epoch_min>    tokens de todo el sitio en el minuto (límite TPM del proveedor)
    llm:req:global:<AAAAMMDD>         peticiones de todo el sitio en el día (límite RPD del proveedor)

Flujo: check() antes de llamar al modelo (y cuenta la petición); record() con el uso REAL que devuelve el
proveedor (usage_metadata) al terminar el stream. Si Redis falla se degrada a contadores locales del pod
(ResilientCounterStore): nunca a "sin límite".
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from nexus_core.infrastructure.logging import log_security_event

from ai_agent_service.security.governor import QuotaExceeded

logger = logging.getLogger(__name__)

DAY = 86_400
MINUTE = 60
_TTL_DAY = DAY + 3_600  # margen por desfase de relojes
_TTL_MINUTE = 2 * MINUTE


def estimate_tokens(text: str) -> int:
    """Estimación conservadora (~3 caracteres por token) para cuando el proveedor no informa el uso."""
    return max(1, math.ceil(len(text) / 3))


class CounterStore(Protocol):
    async def incr(self, key: str, amount: int, ttl: int) -> int: ...

    async def get_many(self, keys: list[str]) -> list[int]: ...


class MemoryCounterStore:
    """Contadores con expiración en memoria del proceso (tests y respaldo cuando Redis no responde)."""

    def __init__(self, clock: Callable[[], float] = time.time, max_keys: int = 100_000) -> None:
        self._clock = clock
        self._data: dict[str, tuple[int, float]] = {}
        self._max_keys = max_keys

    def _purge(self, now: float) -> None:
        if len(self._data) > self._max_keys:
            for k in [k for k, (_, exp) in self._data.items() if exp <= now]:
                del self._data[k]

    async def incr(self, key: str, amount: int, ttl: int) -> int:
        now = self._clock()
        value, expires = self._data.get(key, (0, now + ttl))
        if expires <= now:
            value, expires = 0, now + ttl
        value += amount
        self._data[key] = (value, expires)
        self._purge(now)
        return value

    async def get_many(self, keys: list[str]) -> list[int]:
        now = self._clock()
        out = []
        for k in keys:
            value, expires = self._data.get(k, (0, 0.0))
            out.append(value if expires > now else 0)
        return out


class RedisCounterStore:
    """Contadores compartidos entre pods (INCRBY + EXPIRE en una transacción)."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)

    async def incr(self, key: str, amount: int, ttl: int) -> int:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incrby(key, amount)
            pipe.expire(key, ttl, nx=True)
            value, _ = await pipe.execute()
        return int(value)

    async def get_many(self, keys: list[str]) -> list[int]:
        values = await self._redis.mget(keys)
        return [int(v or 0) for v in values]


class ResilientCounterStore:
    """Usa el almacén principal (Redis) y, si falla, el local: el límite se mantiene aunque Redis caiga."""

    def __init__(self, primary: CounterStore, fallback: CounterStore) -> None:
        self._primary = primary
        self._fallback = fallback
        self.degraded = False

    def _degrade(self, exc: Exception) -> None:
        if not self.degraded:
            self.degraded = True
            log_security_event("llm.budget_degraded", level=logging.ERROR, error=type(exc).__name__)

    async def incr(self, key: str, amount: int, ttl: int) -> int:
        try:
            value = await self._primary.incr(key, amount, ttl)
            self.degraded = False
            return value
        except Exception as exc:  # Redis caído o inaccesible
            self._degrade(exc)
            return await self._fallback.incr(key, amount, ttl)

    async def get_many(self, keys: list[str]) -> list[int]:
        try:
            values = await self._primary.get_many(keys)
            self.degraded = False
            return values
        except Exception as exc:
            self._degrade(exc)
            return await self._fallback.get_many(keys)


class TokenBudget:
    def __init__(
        self,
        store: CounterStore,
        *,
        user_tokens_per_day: int,
        global_tokens_per_day: int,
        global_tokens_per_minute: int,
        global_requests_per_day: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self.user_tokens_per_day = user_tokens_per_day
        self.global_tokens_per_day = global_tokens_per_day
        self.global_tokens_per_minute = global_tokens_per_minute
        self.global_requests_per_day = global_requests_per_day
        self._clock = clock

    def _keys(self, user_key: str) -> tuple[str, str, str, str]:
        now = self._clock()
        day = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y%m%d")
        minute = int(now // MINUTE)
        return (
            f"llm:tok:user:{user_key}:{day}",
            f"llm:tok:global:{day}",
            f"llm:tok:global:min:{minute}",
            f"llm:req:global:{day}",
        )

    def _until_next_day(self) -> int:
        now = self._clock()
        return max(1, DAY - int(now) % DAY)

    def _until_next_minute(self) -> int:
        now = self._clock()
        return max(1, MINUTE - int(now) % MINUTE)

    async def check(self, user_key: str) -> None:
        """Rechaza ANTES de llamar al modelo si algún presupuesto está agotado; si no, cuenta la petición."""
        user_day, global_day, global_minute, requests_day = self._keys(user_key)
        user_tokens, global_tokens, minute_tokens = await self._store.get_many([user_day, global_day, global_minute])
        if global_tokens >= self.global_tokens_per_day:
            raise QuotaExceeded("global_tokens_day", self._until_next_day())
        if minute_tokens >= self.global_tokens_per_minute:
            raise QuotaExceeded("global_tokens_minute", self._until_next_minute())
        if user_tokens >= self.user_tokens_per_day:
            raise QuotaExceeded("user_tokens", self._until_next_day())
        if await self._store.incr(requests_day, 1, _TTL_DAY) > self.global_requests_per_day:
            raise QuotaExceeded("global_requests_day", self._until_next_day())

    async def record(self, user_key: str, tokens: int) -> None:
        """Suma el uso real (o estimado) de una petición terminada. Valores <= 0 se ignoran."""
        tokens = int(tokens)
        if tokens <= 0:
            return
        user_day, global_day, global_minute, _ = self._keys(user_key)
        await self._store.incr(user_day, tokens, _TTL_DAY)
        await self._store.incr(global_day, tokens, _TTL_DAY)
        await self._store.incr(global_minute, tokens, _TTL_MINUTE)

    async def usage(self, user_key: str) -> dict[str, int]:
        user_day, global_day, global_minute, requests_day = self._keys(user_key)
        user, glob, minute, reqs = await self._store.get_many([user_day, global_day, global_minute, requests_day])
        return {"user_tokens_today": user, "global_tokens_today": glob, "global_tokens_minute": minute,
                "global_requests_today": reqs}
