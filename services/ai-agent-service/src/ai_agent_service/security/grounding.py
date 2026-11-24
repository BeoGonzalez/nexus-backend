"""Grounding de importes (LLM07 Misinformation: claim-check antes de que el usuario actúe).

Los importes en CLP que aparecen en la respuesta del modelo se contrastan con los precios reales del catálogo y de la
comparativa externa. Un importe no respaldado no se bloquea (puede ser un cálculo legítimo) pero se avisa al usuario.
Las órdenes nunca usan precios del chat: orders-service consulta el catálogo en el servidor.
"""

from __future__ import annotations

import re

_AMOUNT_RE = re.compile(
    r"\$\s?(\d{1,3}(?:[.,]\d{3})+|\d+)"  # $19.990  $19,990  $19990
    r"|(\d{1,3}(?:[.,]\d{3})+|\d{3,})\s?CLP\b",  # 19.990 CLP  9990 CLP
    re.IGNORECASE,
)


def extract_amounts(text: str) -> set[int]:
    amounts = set()
    for match in _AMOUNT_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2)
        amounts.add(int(re.sub(r"[.,]", "", raw)))
    return amounts


def ungrounded_amounts(text: str, allowed: set[int]) -> set[int]:
    return {a for a in extract_amounts(text) if a not in allowed and a != 0}
