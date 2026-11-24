"""Identidad del usuario final propagada a cada hook (Agentic v2 §2.7.2: las acciones se ejecutan en SU contexto)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserContext:
    sub: str
    email: str | None = None
    email_verified: bool = False
