"""Limitación de intentos para endpoints de autenticación (OWASP A07).

Ventana deslizante en memoria, **por pod**: frena fuerza bruta y credential stuffing contra un mismo email aunque
el atacante rote IPs. El límite global por cliente lo aplica API Gateway (throttling) delante del NLB.
"""

import json
import math
import os
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status

from nexus_core.infrastructure.logging import log_security_event


class SlidingWindowRateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        *,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self.max_keys = max_keys
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._hits)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _window_for(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque()
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)  # descarta la clave menos reciente: memoria acotada
        else:
            self._hits.move_to_end(key)
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def hit(self, key: str) -> bool:
        """Registra un intento; False si la clave superó el máximo en la ventana."""
        with self._lock:
            now = self._clock()
            hits = self._window_for(key, now)
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True

    def retry_after(self, key: str) -> int:
        with self._lock:
            now = self._clock()
            hits = self._window_for(key, now)
            if len(hits) < self.max_requests:
                return 0
            return max(1, math.ceil(hits[0] + self.window - now))


def client_ip(request: Request) -> str:
    """IP del cliente: la entrada de X-Forwarded-For que añadió el proxy de confianza (API Gateway).

    Se toma desde la derecha (`TRUSTED_PROXY_HOPS`, por defecto 1): lo que el cliente antepone se ignora.
    Con 0, o sin cabecera, se usa la IP del peer.
    """
    hops = int(os.getenv("TRUSTED_PROXY_HOPS", "1") or 0)
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if hops > 0 and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else "unknown"


async def _email_from_body(request: Request) -> str | None:
    email = request.query_params.get("email")
    if not email:
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            return None
        email = body.get("email") if isinstance(body, dict) else None
    return email.strip().lower() if isinstance(email, str) and email.strip() else None


def rate_limit(
    scope: str,
    *,
    per_email: SlidingWindowRateLimiter | None = None,
    per_ip: SlidingWindowRateLimiter | None = None,
) -> Callable[[Request], Awaitable[None]]:
    """Dependencia FastAPI: 429 + Retry-After si se supera el límite por email o por IP."""

    async def dependency(request: Request) -> None:
        ip = client_ip(request)
        email = await _email_from_body(request) if per_email is not None else None
        checks = [(per_ip, f"{scope}:ip:{ip}")] if per_ip is not None else []
        if per_email is not None and email:
            checks.append((per_email, f"{scope}:email:{email}"))
        for limiter, key in checks:
            if not limiter.hit(key):
                retry = limiter.retry_after(key)
                log_security_event("auth.rate_limited", scope=scope, client_ip=ip, email=email or "", retry_after=retry)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Demasiados intentos. Inténtalo más tarde.",
                    headers={"Retry-After": str(retry)},
                )

    return dependency
