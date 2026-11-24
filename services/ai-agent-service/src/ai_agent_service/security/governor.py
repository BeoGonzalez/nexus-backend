"""Gobernador de consumo (LLM06 Unbounded Consumption; Agentic v2 §3.3.8 circuit breakers / kill switch).

Límites deterministas ANTES de invocar al proveedor del modelo (cada token cuesta dinero: "denial of wallet"):
- peticiones por minuto y por día por usuario (clave = `sub` del JWT, no la IP),
- streams concurrentes por usuario,
- tope global diario del proceso (techo de gasto),
- kill switch (`enabled=False`).

Estado en memoria **por pod**: con varias réplicas el límite efectivo se multiplica por el número de pods. El throttling
global lo aplica API Gateway; para cuotas exactas entre pods, mover este estado a Redis (siguiente paso).
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

DAY = 86_400.0
MINUTE = 60.0


class QuotaExceeded(Exception):
    def __init__(self, reason: str, retry_after: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


@dataclass
class _UserState:
    minute: deque[float] = field(default_factory=deque)
    day: deque[float] = field(default_factory=deque)
    active: int = 0


class Lease:
    """Reserva de un stream en curso; liberar al terminar (idempotente)."""

    def __init__(self, governor: "UsageGovernor", user_key: str) -> None:
        self._governor = governor
        self._user_key = user_key
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._governor._release(self._user_key)


class UsageGovernor:
    def __init__(
        self,
        *,
        per_minute: int,
        per_day: int,
        max_concurrent: int,
        global_per_day: int,
        enabled: bool = True,
        max_users: int = 50_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.per_minute = per_minute
        self.per_day = per_day
        self.max_concurrent = max_concurrent
        self.global_per_day = global_per_day
        self.enabled = enabled
        self.max_users = max_users
        self._clock = clock
        self._users: OrderedDict[str, _UserState] = OrderedDict()
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    @staticmethod
    def _trim(window: deque[float], now: float, span: float) -> None:
        while window and window[0] <= now - span:
            window.popleft()

    @staticmethod
    def _retry(window: deque[float], now: float, span: float) -> int:
        return max(1, math.ceil(window[0] + span - now)) if window else 1

    def _state(self, user_key: str) -> _UserState:
        state = self._users.get(user_key)
        if state is None:
            state = self._users[user_key] = _UserState()
            while len(self._users) > self.max_users:
                oldest_key, oldest = next(iter(self._users.items()))
                if oldest.active:  # nunca se expulsa a quien tiene un stream abierto
                    self._users.move_to_end(oldest_key)
                    break
                self._users.popitem(last=False)
        else:
            self._users.move_to_end(user_key)
        return state

    def acquire(self, user_key: str) -> Lease:
        with self._lock:
            if not self.enabled:
                raise QuotaExceeded("disabled", 60)
            now = self._clock()
            state = self._state(user_key)
            self._trim(state.minute, now, MINUTE)
            self._trim(state.day, now, DAY)
            self._trim(self._global, now, DAY)
            if state.active >= self.max_concurrent:
                raise QuotaExceeded("concurrency", 5)
            if len(state.minute) >= self.per_minute:
                raise QuotaExceeded("per_minute", self._retry(state.minute, now, MINUTE))
            if len(state.day) >= self.per_day:
                raise QuotaExceeded("per_day", self._retry(state.day, now, DAY))
            if len(self._global) >= self.global_per_day:
                raise QuotaExceeded("global_budget", self._retry(self._global, now, DAY))
            state.minute.append(now)
            state.day.append(now)
            self._global.append(now)
            state.active += 1
            return Lease(self, user_key)

    def _release(self, user_key: str) -> None:
        with self._lock:
            state = self._users.get(user_key)
            if state and state.active > 0:
                state.active -= 1

    def usage(self, user_key: str) -> dict[str, int]:
        with self._lock:
            state = self._users.get(user_key) or _UserState()
            return {"minute": len(state.minute), "day": len(state.day), "active": state.active}
