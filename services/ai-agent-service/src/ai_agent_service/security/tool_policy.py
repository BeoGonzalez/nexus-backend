"""Política de la herramienta de correo (hook toolCallRequest; LLM03 Excessive Agency, ASI Rule of Two).

El agente lee entrada no confiable (usuario, web, RAG). Si además pudiera escribir a CUALQUIER dirección, un prompt
injection lo convertiría en un relay de phishing desde la cuenta de la tienda. Por eso:
- el destinatario sale SOLO de la identidad verificada del token (complete mediation, en código, no en el prompt),
- el cuerpo generado por el modelo se escapa como texto (LLM10),
- hay un presupuesto de envíos por usuario (circuit breaker de herramienta).
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass

from nexus_security.rate_limit import SlidingWindowRateLimiter

from ai_agent_service.security.context import UserContext


@dataclass(frozen=True)
class ToolDecision:
    allowed: bool
    reason: str
    recipient: str | None = None


class EmailToolPolicy:
    def __init__(self, per_hour: int = 3, clock=time.monotonic) -> None:
        self._limiter = SlidingWindowRateLimiter(max_requests=per_hour, window_seconds=3600, clock=clock)

    def authorize(self, user: UserContext) -> ToolDecision:
        email = (user.email or "").strip().lower()
        if not email:
            return ToolDecision(False, "no_email_in_token")
        if not user.email_verified:
            return ToolDecision(False, "email_not_verified")
        if not self._limiter.hit(f"email:{user.sub}"):
            return ToolDecision(False, "rate_limited")
        return ToolDecision(True, "allowed", recipient=email)


def render_email_body(model_output: str) -> str:
    """El texto del modelo se inserta como texto plano escapado dentro de una plantilla fija."""
    safe = html.escape(model_output, quote=True).replace("\n", "<br>")
    return (
        '<div style="font-family:Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.5">'
        f"{safe}"
        '<p style="color:#64748b;font-size:12px">Mensaje generado por NexusBot (IA). '
        "Verifica precios y stock en la tienda antes de comprar.</p></div>"
    )
