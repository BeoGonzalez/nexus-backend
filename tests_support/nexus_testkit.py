"""Utilidades compartidas por las suites de prueba de todos los servicios."""

from __future__ import annotations

import time

import jwt
from pydantic import BaseModel

TEST_JWT_SECRET = "test-secret-not-for-prod-0123456789abcdef"


def sign_token(
    sub: str = "user-1",
    email: str | None = "buyer@nexus.cl",
    role: str = "customer",
    exp_delta_s: int = 3600,
    secret: str = TEST_JWT_SECRET,
    email_verified: bool = True,
) -> str:
    claims = {"sub": sub, "role": role, "exp": int(time.time()) + exp_delta_s}
    if email is not None:
        claims["email"] = email
        claims["email_verified"] = email_verified
    return jwt.encode(claims, secret, algorithm="HS256")


def auth_headers(**kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {sign_token(**kwargs)}"}


class FakePublisher:
    """Sustituto de nexus_events.publisher.EventPublisher que registra lo publicado."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, BaseModel]] = []
        self.raw: list[tuple[str, str]] = []

    async def connect(self) -> None:  # pragma: no cover - interfaz
        return None

    async def publish(self, routing_key: str, event: BaseModel, exchange_name: str = "nexus_events") -> None:
        if self.fail:
            raise ConnectionError("broker caído (simulado)")
        self.published.append((routing_key, event))

    async def publish_raw(self, event_type: str, payload_json: str) -> None:
        if self.fail:
            raise ConnectionError("broker caído (simulado)")
        self.raw.append((event_type, payload_json))

    async def close(self) -> None:
        return None
