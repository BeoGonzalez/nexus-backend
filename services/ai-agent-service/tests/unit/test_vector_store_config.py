"""El ai-agent debe consultar el índice de Pinecone que existe (nexus-catalog), no uno inexistente."""

from ai_agent_service.config import Settings


def test_default_pinecone_index_is_the_catalog_index(monkeypatch):
    monkeypatch.delenv("PINECONE_INDEX_NAME", raising=False)
    monkeypatch.delenv("PINECONE_NAMESPACE", raising=False)
    s = Settings(_env_file=None)
    assert s.PINECONE_INDEX_NAME == "nexus-catalog"
    assert s.PINECONE_NAMESPACE == "catalog"


def test_embedding_settings_point_to_pinned_onnx_model(monkeypatch):
    monkeypatch.delenv("EMBEDDING_ONNX_FILE", raising=False)
    s = Settings(_env_file=None)
    assert s.EMBEDDING_MODEL_REVISION == "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    assert s.EMBEDDING_ONNX_FILE == "onnx/model_quint8_avx2.onnx"
