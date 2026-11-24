"""Reindexado del catálogo en Pinecone: registros con el formato que lee PineconeVectorStoreAdapter."""

from ai_agent_service.infrastructure.catalog_indexer import build_records, document_text, stale_ids
from ai_agent_service.infrastructure.pinecone_store import PineconeVectorStoreAdapter

PRODUCT = {
    "id": "e6146c60-7232-467b-869f-54efa743f9ba",
    "title": "Marvel's Spider-Man 2",
    "description": "Los Spider-Men regresan a Nueva York.",
    "price_clp": 49990,
    "stock": 25,
    "image_url": "https://images.unsplash.com/photo-1?w=800",
    "platform": {"id": "p1", "name": "PS5"},
    "genres": [{"id": "g1", "name": "Acción"}, {"id": "g2", "name": "Aventura"}],
}


class FakeEmbedder:
    def __init__(self):
        self.texts = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[0.1] * 384 for _ in texts]


def test_document_text_combines_title_platform_genres_and_description():
    text = document_text(PRODUCT)
    for part in ("Marvel's Spider-Man 2", "PS5", "Acción", "Aventura", "Los Spider-Men regresan"):
        assert part in text


def test_records_carry_vector_and_metadata_the_vector_store_reads():
    embedder = FakeEmbedder()
    [record] = build_records([PRODUCT], embedder)
    assert record["id"] == PRODUCT["id"]
    assert len(record["values"]) == 384
    assert embedder.texts == [document_text(PRODUCT)]
    # Debe poder leerse de vuelta con el adaptador del ai-agent sin perder datos.
    game = PineconeVectorStoreAdapter._match_to_entity(None, {"id": record["id"], "metadata": record["metadata"]})
    assert str(game.id) == PRODUCT["id"]
    assert game.title == "Marvel's Spider-Man 2"
    assert game.price_clp == 49990 and game.stock == 25
    assert [g.name for g in game.genres] == ["Acción", "Aventura"]
    assert game.image_url == PRODUCT["image_url"]


def test_metadata_is_bounded_and_skips_invalid_products():
    long = dict(PRODUCT, id="11111111-1111-1111-1111-111111111111", description="x" * 10_000)
    no_title = dict(PRODUCT, id="22222222-2222-2222-2222-222222222222", title="  ")
    bad_id = dict(PRODUCT, id="no-es-un-uuid")
    records = build_records([long, no_title, bad_id], FakeEmbedder())
    assert [r["id"] for r in records] == [long["id"]]
    assert len(records[0]["metadata"]["description"]) <= 1000


def test_stale_ids_are_the_ones_no_longer_in_the_catalog():
    assert stale_ids(existing={"a", "b", "c"}, current={"b", "c", "d"}) == {"a"}
