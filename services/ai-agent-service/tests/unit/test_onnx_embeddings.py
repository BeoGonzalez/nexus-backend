"""Embeddings ONNX sin PyTorch (paraphrase-multilingual-MiniLM-L12-v2, cuantizado).

Estos tests usan el modelo REAL (se descarga una vez de Hugging Face, revisión fijada y SHA-256 verificado):
la paridad con PyTorch y la calidad semántica no se pueden probar con un fake.
"""

import json
import math
from pathlib import Path

import pytest

from ai_agent_service.infrastructure import embeddings
from ai_agent_service.infrastructure.embeddings import (
    MODEL_FILES,
    EmbeddingUnavailableError,
    OnnxSentenceEmbedder,
    download_model,
    verify_model_dir,
)

REFERENCE = json.loads((Path(__file__).parents[1] / "fixtures" / "minilm_torch_reference.json").read_text(encoding="utf-8"))


def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


@pytest.fixture(scope="session")
def model_dir(tmp_path_factory):
    return download_model(tmp_path_factory.mktemp("minilm"))


@pytest.fixture(scope="session")
def embedder(model_dir):
    return OnnxSentenceEmbedder(model_dir)


def test_vectors_have_384_dims_and_unit_norm(embedder):
    v = embedder.embed_query("Hades II")
    assert len(v) == 384
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-4)


@pytest.mark.parametrize("item", REFERENCE["items"], ids=lambda i: i["text"][:25])
def test_matches_pytorch_sentence_transformers(embedder, item):
    # Mismos pesos (export ONNX oficial, cuantizado int8): la dirección del vector se conserva.
    assert cos(embedder.embed_query(item["text"]), item["vector"]) >= 0.97


def test_batch_equals_individual_queries(embedder):
    texts = [i["text"] for i in REFERENCE["items"]]
    batch = embedder.embed(texts)
    for text, vec in zip(texts, batch):
        assert cos(vec, embedder.embed_query(text)) >= 0.9999


def test_semantic_ranking_finds_the_relevant_game(embedder):
    docs = {
        "terror": "Resident Evil 4 Terror, Supervivencia Sobrevive a una aldea infestada con recursos limitados.",
        "carreras": "Forza Horizon 5 Carreras, Mundo abierto Conduce cientos de autos por México.",
        "granja": "Stardew Valley Simulación, Granja Cultiva tu granja y haz amigos en el pueblo.",
    }
    q = embedder.embed_query("quiero un juego de miedo para sobrevivir")
    ranked = sorted(docs, key=lambda k: cos(q, embedder.embed_query(docs[k])), reverse=True)
    assert ranked[0] == "terror"


def test_long_input_is_truncated_not_rejected(embedder):
    v = embedder.embed_query("palabra " * 5000)
    assert len(v) == 384


def test_tampered_model_file_is_rejected(model_dir, tmp_path):
    # LLM03 Supply Chain: un archivo que no coincide con el SHA-256 fijado no se carga.
    for name in MODEL_FILES:
        dst = tmp_path / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((model_dir / name).read_bytes())
    tok = tmp_path / "tokenizer.json"
    tok.write_bytes(tok.read_bytes() + b" ")
    with pytest.raises(EmbeddingUnavailableError):
        verify_model_dir(tmp_path)


def test_missing_model_files_are_rejected(tmp_path):
    with pytest.raises(EmbeddingUnavailableError):
        verify_model_dir(tmp_path)


def test_no_silent_hash_fallback_exists():
    # El fallback por hash llenó Pinecone de vectores sin significado: no debe volver a existir.
    assert not hasattr(embeddings, "_FallbackEmbedder")


def test_torch_is_not_imported(embedder):
    import sys

    embedder.embed_query("hola")
    assert "torch" not in sys.modules
