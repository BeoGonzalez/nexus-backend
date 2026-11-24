"""Reindexa el catálogo en Pinecone con los embeddings ONNX del ai-agent.

Uso (desde la raíz del monorepo):
    .venv/Scripts/python.exe services/ai-agent-service/scripts/reindex_catalog.py \
        --catalog-url https://<api-id>.execute-api.us-east-1.amazonaws.com/v1/api/v1/catalog [--dry-run]

Lee PINECONE_API_KEY / PINECONE_INDEX_NAME / PINECONE_NAMESPACE del entorno (o .env). Ejecútalo cada vez que
cambie el catálogo: los precios y el stock que ve el asistente salen de estos metadatos.
"""

from __future__ import annotations

import argparse
import sys

import httpx
from pinecone import Pinecone

from ai_agent_service.config import get_settings
from ai_agent_service.infrastructure.catalog_indexer import build_records, stale_ids
from ai_agent_service.infrastructure.embeddings import get_embedder

PAGE = 100


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog-url", required=True)
    parser.add_argument("--dry-run", action="store_true", help="calcula los vectores sin escribir en Pinecone")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.PINECONE_API_KEY:
        print("Falta PINECONE_API_KEY", file=sys.stderr)
        return 1

    products = fetch_products(args.catalog_url)
    records = build_records(products, get_embedder())
    print(f"Catálogo: {len(products)} productos -> {len(records)} registros válidos "
          f"(índice {settings.PINECONE_INDEX_NAME}, namespace {settings.PINECONE_NAMESPACE})")
    if args.dry_run:
        return 0

    index = Pinecone(api_key=settings.PINECONE_API_KEY).Index(settings.PINECONE_INDEX_NAME)
    ns = settings.PINECONE_NAMESPACE
    for i in range(0, len(records), 50):
        index.upsert(vectors=records[i:i + 50], namespace=ns)

    existing = {vid for page in index.list(namespace=ns) for vid in page}
    orphans = stale_ids(existing, {r["id"] for r in records})
    if orphans:
        index.delete(ids=sorted(orphans), namespace=ns)
    print(f"Upsert: {len(records)} | huérfanos borrados: {len(orphans)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
