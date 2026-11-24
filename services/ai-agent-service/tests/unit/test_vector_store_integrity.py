"""LLM05 / LLM09: solo entran al contexto vectores generados por NUESTRO modelo y suficientemente similares.

El índice de Pinecone llegó a contener vectores sin significado (fallback por hash): un vector escrito por otro
proceso u otro modelo (o envenenado) no debe llegar al prompt.
"""

import uuid

from ai_agent_service.infrastructure.catalog_indexer import build_records
from ai_agent_service.infrastructure.embeddings import EMBEDDING_TAG
from ai_agent_service.infrastructure.pinecone_store import PineconeVectorStoreAdapter


class FakeIndex:
    def __init__(self, matches):
        self.matches = matches
        self.kwargs = None

    def query(self, **kwargs):
        self.kwargs = kwargs
        return {"matches": self.matches}


def match(score, tag=EMBEDDING_TAG, title="Hades II"):
    gid = str(uuid.uuid4())
    md = {"id": gid, "title": title, "description": "", "price_clp": 9990, "stock": 3, "genres": "Roguelike"}
    if tag is not None:
        md["embedding_model"] = tag
    return {"id": gid, "score": score, "metadata": md}


def adapter(matches, min_score=0.3):
    a = object.__new__(PineconeVectorStoreAdapter)  # sin __init__: los tests no construyen proveedores reales
    a._index, a._index_name, a._namespace, a._fallback = FakeIndex(matches), "nexus-catalog", "catalog", None
    a._min_score, a._model_tag = min_score, EMBEDDING_TAG
    return a


async def test_query_asks_pinecone_only_for_vectors_of_our_embedding_model():
    a = adapter([match(0.8)])
    await a.similarity_search([0.1] * 384, top_k=3)
    assert a._index.kwargs["filter"] == {"embedding_model": {"$eq": EMBEDDING_TAG}}


async def test_foreign_or_untagged_vectors_are_dropped_even_if_returned():
    a = adapter([match(0.9, tag="otro-modelo", title="Envenenado"), match(0.9, tag=None, title="Sin marca"),
                 match(0.7, title="Legítimo")])
    result = await a.similarity_search([0.1] * 384, top_k=5)
    assert [g.title for g in result] == ["Legítimo"]


async def test_low_similarity_results_do_not_reach_the_prompt():
    a = adapter([match(0.62, title="Relevante"), match(0.21, title="Ruido")])
    result = await a.similarity_search([0.1] * 384, top_k=5)
    assert [g.title for g in result] == ["Relevante"]


def test_indexer_tags_every_vector_with_the_embedding_model():
    class E:
        def embed(self, texts):
            return [[0.0] * 384 for _ in texts]

    [record] = build_records([{"id": str(uuid.uuid4()), "title": "Celeste", "genres": []}], E())
    assert record["metadata"]["embedding_model"] == EMBEDDING_TAG
