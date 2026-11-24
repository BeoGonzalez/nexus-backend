"""Construcción de registros de Pinecone a partir del catálogo (para el script scripts/reindex_catalog.py).

El texto indexado y los metadatos siguen el formato que lee PineconeVectorStoreAdapter._match_to_entity.
LLM09 (vector store): solo productos con UUID y título válidos, metadatos acotados (sin campos arbitrarios).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol
from uuid import UUID

MAX_TITLE = 200
MAX_DESCRIPTION = 1000
MAX_GENRES = 10


class TextEmbedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _genres(product: Mapping[str, Any]) -> list[str]:
    names = [str(g.get("name", "")).strip() for g in product.get("genres") or [] if isinstance(g, Mapping)]
    return [n[:50] for n in names if n][:MAX_GENRES]


def _platform(product: Mapping[str, Any]) -> str:
    platform = product.get("platform")
    return str(platform.get("name", "")).strip()[:50] if isinstance(platform, Mapping) else ""


def document_text(product: Mapping[str, Any]) -> str:
    """Texto que se convierte en vector: título, plataforma, géneros y descripción."""
    parts = [str(product.get("title", "")).strip(), _platform(product), ", ".join(_genres(product)),
             str(product.get("description", "")).strip()[:MAX_DESCRIPTION]]
    return " | ".join(p for p in parts if p)


def _is_valid(product: Mapping[str, Any]) -> bool:
    try:
        UUID(str(product.get("id")))
    except (ValueError, TypeError):
        return False
    return bool(str(product.get("title", "")).strip())


def build_records(products: Iterable[Mapping[str, Any]], embedder: TextEmbedder) -> list[dict[str, Any]]:
    valid = [p for p in products if _is_valid(p)]
    vectors = embedder.embed([document_text(p) for p in valid])
    records = []
    for product, vector in zip(valid, vectors):
        records.append({
            "id": str(product["id"]),
            "values": vector,
            "metadata": {
                "id": str(product["id"]),
                "title": str(product["title"]).strip()[:MAX_TITLE],
                "description": str(product.get("description", "")).strip()[:MAX_DESCRIPTION],
                "price_clp": int(product.get("price_clp") or 0),
                "stock": int(product.get("stock") or 0),
                "genres": ", ".join(_genres(product)),
                "platform": _platform(product),
                "image_url": str(product.get("image_url") or "")[:500],
            },
        })
    return records


def stale_ids(existing: set[str], current: set[str]) -> set[str]:
    """Vectores del índice cuyo producto ya no existe en el catálogo (se borran para no recomendarlos)."""
    return set(existing) - set(current)
