"""Reindexado ejecutable dentro del pod (python -m ai_agent_service.cli.reindex_catalog), sin scripts/ en la imagen."""

import importlib

from ai_agent_service.cli.reindex_catalog import sync_index


class FakeIndex:
    def __init__(self, existing):
        self.existing, self.upserts, self.deleted = list(existing), [], []

    def upsert(self, vectors, namespace):
        self.upserts.append((len(vectors), namespace))

    def list(self, namespace):
        yield self.existing

    def delete(self, ids, namespace):
        self.deleted.append((ids, namespace))


def records(n):
    return [{"id": f"id-{i}", "values": [0.0], "metadata": {}} for i in range(n)]


def test_upserts_in_batches_and_deletes_only_orphans():
    index = FakeIndex(existing=["id-0", "viejo-1", "viejo-2"])
    upserted, orphans = sync_index(index, records(120), namespace="catalog")
    assert index.upserts == [(50, "catalog"), (50, "catalog"), (20, "catalog")]
    assert index.deleted == [(["viejo-1", "viejo-2"], "catalog")]
    assert (upserted, orphans) == (120, 2)


def test_never_wipes_the_index_when_the_catalog_comes_back_empty():
    index = FakeIndex(existing=["id-0", "id-1"])
    assert sync_index(index, [], namespace="catalog") == (0, 0)
    assert index.deleted == []  # un catálogo vacío (o caído) no debe vaciar Pinecone


def test_module_is_importable_from_the_installed_package():
    assert importlib.import_module("ai_agent_service.cli.reindex_catalog").main
