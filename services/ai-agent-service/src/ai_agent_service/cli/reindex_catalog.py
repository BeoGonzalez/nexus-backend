"""Reindexa el catálogo en Pinecone con los embeddings ONNX del ai-agent.

Uso dentro del pod (el pipeline lo ejecuta tras cada despliegue):
    python -m ai_agent_service.cli.reindex_catalog --catalog-url http://catalog/api/v1/catalog [--dry-run]

Lee PINECONE_API_KEY / PINECONE_INDEX_NAME / PINECONE_NAMESPACE del entorno. Los IDs de Pinecone son los IDs de
producto: si el catálogo se recrea (p. ej. seed en otra cuenta), sin reindexar el asistente no encuentra juegos.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

import httpx

PAGE = 100
BATCH = 50


def fetch_products(catalog_url: str) -> list[dict]:
    products: list[dict] = []
    with httpx.Client(timeout=30) as client:
        while True:
            r = client.get(f"{catalog_url.rstrip('/')}/products", params={"skip": len(products), "limit": PAGE})
            r.raise_for_status()
            page = r.json()
            products.extend(page)
            if len(page) < PAGE:
                return products


def sync_index(index: Any, records: list[dict], namespace: str) -> tuple[int, int]:
    """Upsert por lotes y borrado de huérfanos. Con 0 registros no toca nada: nunca vacía el índice."""
    if not records:
        return 0, 0
    from ai_agent_service.infrastructure.catalog_indexer import stale_ids

    for i in range(0, len(records), BATCH):
        index.upsert(vectors=records[i:i + BATCH], namespace=namespace)
    existing = {vid for page in index.list(namespace=namespace) for vid in page}
    orphans = sorted(stale_ids(existing, {r["id"] for r in records}))
    if orphans:
        index.delete(ids=orphans, namespace=namespace)
    return len(records), len(orphans)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--catalog-url", required=True)
    parser.add_argument("--dry-run", action="store_true", help="calcula los vectores sin escribir en Pinecone")
    args = parser.parse_args(argv)

    from ai_agent_service.config import get_settings
    from ai_agent_service.infrastructure.catalog_indexer import build_records
    from ai_agent_service.infrastructure.embeddings import get_embedder

    settings = get_settings()
    if not settings.PINECONE_API_KEY:
        print("Falta PINECONE_API_KEY", file=sys.stderr)
        return 1

    products = fetch_products(args.catalog_url)
    records = build_records(products, get_embedder())
    print(f"Catálogo: {len(products)} productos -> {len(records)} registros válidos "
          f"(índice {settings.PINECONE_INDEX_NAME}, namespace {settings.PINECONE_NAMESPACE})")
    if not records:
        print("Catálogo vacío o sin registros válidos: no se modifica el índice", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0

    from pinecone import Pinecone

    index = Pinecone(api_key=settings.PINECONE_API_KEY).Index(settings.PINECONE_INDEX_NAME)
    upserted, orphans = sync_index(index, records, settings.PINECONE_NAMESPACE)
    print(f"Upsert: {upserted} | huérfanos borrados: {orphans}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
