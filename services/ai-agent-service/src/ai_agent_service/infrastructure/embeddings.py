import asyncio
from functools import lru_cache

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:
    HuggingFaceEmbeddings = None

from ai_agent_service.config import get_settings


class _FallbackEmbedder:
    """Embedder determinista de fallback para entornos donde no esté disponible PyTorch / HuggingFace."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed_query(self, text: str) -> list[float]:
        # Vector seudoaleatorio determinista normalizado basado en hash
        import hashlib
        h = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        vec = [((h >> (i % 64)) & 0xFF) / 255.0 for i in range(self.dimensions)]
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm for x in vec]


class HuggingFaceEmbeddingAdapter:
    def __init__(self, model_name: str, revision: str | None = None) -> None:
        self._model = _get_embedding_model(model_name, revision or get_settings().EMBEDDING_MODEL_REVISION)

    async def embed_text(self, text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._model.embed_query, text)
        return result


@lru_cache(maxsize=1)
def _get_embedding_model(model_name: str, revision: str):
    if HuggingFaceEmbeddings is not None:
        try:
            return HuggingFaceEmbeddings(
                model_name=model_name,
                # LLM04 Supply Chain: commit fijado y sin ejecutar código remoto del repo del modelo.
                model_kwargs={"device": "cpu", "revision": revision, "trust_remote_code": False},
                encode_kwargs={"normalize_embeddings": True},
            )
        except Exception:
            pass
    return _FallbackEmbedder()
