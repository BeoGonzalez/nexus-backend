"""Embeddings de texto con ONNX Runtime (sin PyTorch).

Modelo: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2, export ONNX oficial cuantizado (int8 AVX2)
del mismo commit fijado. Reproduce el pipeline de SentenceTransformer: tokenizar (máx. 128 tokens) -> transformer
-> mean pooling con la attention mask -> normalización L2. Vectores de 384 dimensiones.

Seguridad (OWASP LLM03 Supply Chain): revisión fijada, SHA-256 de cada archivo verificado antes de cargarlo,
sin código remoto. Si el modelo no está disponible se lanza EmbeddingUnavailableError: NUNCA se devuelven
vectores inventados (el antiguo fallback por hash llenó el índice de vectores sin significado).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

from ai_agent_service.config import get_settings

logger = logging.getLogger(__name__)

MAX_SEQ_LENGTH = 128  # sentence_bert_config.json del modelo
DIMENSIONS = 384
# Marca que se guarda con cada vector indexado: la búsqueda solo acepta vectores de este modelo (LLM05/LLM09).
EMBEDDING_TAG = "minilm-l12-onnx-int8@e8f8c211226b"

# SHA-256 de los archivos en la revisión e8f8c211226b894fcb81acc59f3b34ba3efd5f42 (metadatos LFS de Hugging Face).
MODEL_FILES: dict[str, str] = {
    "onnx/model_quint8_avx2.onnx": "98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f",
    "tokenizer.json": "2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8",
}


class EmbeddingUnavailableError(RuntimeError):
    """El modelo de embeddings no se pudo cargar o no pasó la verificación de integridad."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_model_dir(model_dir: str | Path) -> Path:
    """Comprueba que el directorio tenga cada archivo del modelo con su SHA-256 fijado."""
    root = Path(model_dir)
    for name, expected in MODEL_FILES.items():
        path = root / name
        if not path.is_file():
            raise EmbeddingUnavailableError(f"Falta el archivo del modelo: {name}")
        if _sha256(path) != expected:
            raise EmbeddingUnavailableError(f"SHA-256 inesperado en {name}: archivo alterado o revisión distinta")
    return root


def download_model(target_dir: str | Path, repo_id: str | None = None, revision: str | None = None) -> Path:
    """Descarga los archivos fijados del modelo (revisión exacta) a target_dir y verifica su integridad."""
    from huggingface_hub import hf_hub_download

    settings = get_settings()
    root = Path(target_dir)
    for name in MODEL_FILES:
        hf_hub_download(
            repo_id=repo_id or settings.EMBEDDING_MODEL_NAME,
            filename=name,
            revision=revision or settings.EMBEDDING_MODEL_REVISION,
            local_dir=root,
        )
    return verify_model_dir(root)


class OnnxSentenceEmbedder:
    """Equivalente a SentenceTransformer.encode(..., normalize_embeddings=True) con ONNX Runtime."""

    def __init__(self, model_dir: str | Path, onnx_file: str = "onnx/model_quint8_avx2.onnx", threads: int = 1) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        root = verify_model_dir(model_dir)
        self._tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=MAX_SEQ_LENGTH)
        self._tokenizer.enable_padding(pad_id=self._tokenizer.token_to_id("<pad>") or 1, pad_token="<pad>")

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads  # pods con 1 vCPU: más hilos solo compiten entre sí
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(root / onnx_file), options, providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Uno por uno a propósito: la cuantización dinámica int8 calcula sus rangos sobre todo el lote (padding
        # incluido), así que un texto en lote da un vector ligeramente distinto que solo. Indexar y consultar
        # deben producir exactamente el mismo vector.
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        encodings = self._tokenizer.encode_batch([text])
        ids = np.array([e.ids for e in encodings], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, feed)[0]  # (batch, tokens, 384)
        weights = mask[..., None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1e-9, None)
        pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
        return pooled[0].astype(float).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


@lru_cache(maxsize=1)
def get_embedder() -> OnnxSentenceEmbedder:
    """Un embedder por proceso. Usa el modelo integrado en la imagen o lo descarga (revisión fijada) a la caché."""
    settings = get_settings()
    try:
        if settings.EMBEDDING_MODEL_DIR:
            model_dir = Path(settings.EMBEDDING_MODEL_DIR)
        else:
            cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "nexus-minilm"
            model_dir = cache if _is_complete(cache) else download_model(cache)
        return OnnxSentenceEmbedder(model_dir, onnx_file=settings.EMBEDDING_ONNX_FILE)
    except EmbeddingUnavailableError:
        raise
    except Exception as exc:
        raise EmbeddingUnavailableError(f"No se pudo cargar el modelo de embeddings: {type(exc).__name__}") from exc


def _is_complete(model_dir: Path) -> bool:
    try:
        verify_model_dir(model_dir)
        return True
    except EmbeddingUnavailableError:
        return False


class OnnxEmbeddingAdapter:
    """Puerto EmbeddingPort sobre el embedder ONNX (inferencia en un hilo para no bloquear el event loop)."""

    def __init__(self, model_name: str | None = None) -> None:
        # Carga diferida: si el modelo no está, falla embed_text (el chat se degrada a "sin catálogo")
        # en vez de tumbar la construcción del servicio.
        self._model_name = model_name

    async def embed_text(self, text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: get_embedder().embed_query(text))

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: get_embedder().embed(texts))
