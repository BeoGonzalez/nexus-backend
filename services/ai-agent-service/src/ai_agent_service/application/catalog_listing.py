"""Preguntas del tipo "¿qué juegos tienen?": se responden con el catálogo completo EN VIVO.

La búsqueda semántica devuelve como mucho los 10 vecinos más cercanos, así que nunca puede enumerar el
catálogo. Para un listado, el contexto se arma con todos los productos del servicio de catálogo (fuente de
verdad: Aurora), en una línea compacta por juego para acotar los tokens (LLM06), y se filtra por plataforma o
género si la pregunta los menciona.
"""

from __future__ import annotations

import re
import unicodedata

from ai_agent_service.domain.entities import VideoGame

MAX_LISTED_GAMES = 50
MAX_PRODUCT_CARDS = 10

_LISTING_PATTERNS = [
    r"\b(que|cuales)\b.*\bjuegos\b.*\b(tienen|tienes|hay|venden|vendes|ofrecen|disponibles|son)\b",
    r"\bcatalogo\b",
    r"\b(lista|listado)\b.*\bjuegos\b",
    r"\btodos\s+(los\s+)?(juegos|titulos)\b",
    r"\bjuegos\s+disponibles\b",
]

# Alias de la pregunta -> nombre de la plataforma en el catálogo.
_PLATFORM_ALIASES = {
    "PS5": ("ps5", "playstation", "play station", "play 5"),
    "PC": ("pc", "computador", "steam"),
    "Xbox Series": ("xbox",),
    "Switch 2": ("switch", "nintendo"),
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def is_catalog_listing_query(query: str) -> bool:
    q = _normalize(query)
    return any(re.search(p, q) for p in _LISTING_PATTERNS)


def _words(text: str) -> str:
    """Texto normalizado como palabras separadas por un espacio, con bordes: ' que juegos de ps5 '."""
    return f" {' '.join(re.findall(r'[a-z0-9]+', _normalize(text)))} "


def filter_listing(games: list[VideoGame], query: str) -> list[VideoGame]:
    """Filtra por la plataforma o los géneros mencionados; si nada coincide, devuelve el catálogo completo."""
    q = _words(query)
    platforms = {name for name, aliases in _PLATFORM_ALIASES.items() if any(_words(a) in q for a in aliases)}
    genres = {_words(g.name) for vg in games for g in vg.genres if g.name and _words(g.name) in q}

    selected = [
        vg for vg in games
        if (not platforms or vg.platform in platforms)
        and (not genres or any(_words(g.name) in genres for g in vg.genres))
    ]
    return selected or games


def format_catalog_listing(games: list[VideoGame]) -> str:
    lines = []
    for i, vg in enumerate(games, 1):
        parts = [vg.title[:200]]
        if vg.platform:
            parts.append(vg.platform[:50])
        parts.append(f"${vg.price_clp} CLP")
        genres = ", ".join(g.name for g in vg.genres if g.name)[:120]
        if genres:
            parts.append(genres)
        parts.append(f"Stock: {vg.stock}" if vg.stock > 0 else "SIN STOCK")
        lines.append(f"{i}. " + " — ".join(parts))
    return "\n".join(lines)
