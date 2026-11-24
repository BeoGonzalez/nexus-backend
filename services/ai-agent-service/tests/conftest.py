import json
import uuid

import httpx
import pytest

from ai_agent_service.domain.entities import Genre, VideoGame


def game(title="Hades II", price=19990, stock=4) -> VideoGame:
    return VideoGame(id=uuid.uuid4(), title=title, description="Roguelike de dioses griegos", price_clp=price,
                     stock=stock, genres=[Genre(name="Roguelike")])


class FakeEmbedding:
    async def embed_text(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeVectorStore:
    def __init__(self, games=None, fail: bool = False) -> None:
        self.games = [game()] if games is None else games
        self.fail = fail

    async def similarity_search(self, embedding, top_k=5):
        if self.fail:
            raise ConnectionError("Pinecone caído (simulado)")
        return self.games[:top_k]


class FakeLLM:
    def __init__(self, chunks=("Te ", "recomiendo ", "Hades II"), fail: bool = False, usage: dict | None = None) -> None:
        self.chunks = chunks
        self.fail = fail
        self.usage = usage
        self.prompts: list[str] = []

    async def generate(self, system_prompt: str, user_message: str) -> str:
        self.prompts.append(user_message)
        return "".join(self.chunks)

    async def generate_stream(self, system_prompt: str, user_message: str, usage: dict | None = None):
        self.prompts.append(user_message)
        if self.fail:
            raise RuntimeError("Groq caído (simulado)")
        for c in self.chunks:
            yield c
        if usage is not None and self.usage:
            usage.update(self.usage)


class FakeDecision:
    def __init__(self, intent="recommendation", need_trivia=True) -> None:
        self.intent, self.need_trivia = intent, need_trivia

    async def classify_intent(self, query: str) -> str:
        return self.intent

    async def evaluate_decision(self, query: str) -> dict:
        return {"intent": self.intent, "need_trivia": self.need_trivia}


class FakeKnowledge:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch_trivia(self, topic: str) -> str:
        self.calls.append(topic)
        return f"Trivia de {topic}"


class FakeNews:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch_news(self, query: str) -> str:
        self.calls.append(query)
        return f"Noticia sobre {query}"


class FakePrices:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def compare_price(self, game_title: str, nexus_price_clp: int) -> dict:
        self.calls.append((game_title, nexus_price_clp))
        return {"has_data": True, "comparison_summary": f"Steam vende {game_title} más caro"}


def parse_sse(raw: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in raw.splitlines() if line.startswith("data: ")]


@pytest.fixture(autouse=True)
def forbid_real_providers(monkeypatch):
    """Ningún test puede construir el LLM de Groq, Pinecone ni el modelo de embeddings real."""
    from ai_agent_service.infrastructure import embeddings, llm, pinecone_store

    def _boom(*_a, **_k):
        raise AssertionError("se intentó construir un proveedor real durante los tests")

    monkeypatch.setattr(llm.GroqLLMAdapter, "__init__", _boom)
    monkeypatch.setattr(pinecone_store.PineconeVectorStoreAdapter, "__init__", _boom)
    monkeypatch.setattr(embeddings.OnnxEmbeddingAdapter, "__init__", _boom)


@pytest.fixture
def make_game():
    return game


@pytest.fixture
def sse():
    return parse_sse


@pytest.fixture
def ports():
    return {
        "embedding_port": FakeEmbedding(),
        "llm_port": FakeLLM(),
        "vector_store_port": FakeVectorStore(),
        "external_knowledge_port": FakeKnowledge(),
        "decision_port": FakeDecision(),
        "gaming_news_port": FakeNews(),
        "price_comparison_port": FakePrices(),
    }


@pytest.fixture
def service(ports):
    from ai_agent_service.application.services import AssistantService

    return AssistantService(**ports)


@pytest.fixture
async def client(ports, monkeypatch):
    from langgraph.checkpoint.memory import MemorySaver

    from ai_agent_service.application.services import AssistantService
    from ai_agent_service.main import app
    from ai_agent_service.presentation import router

    # Igual que en producción: el servicio usa el checkpointer compartido del router,
    # que es el que limpia DELETE /session/{id}. Aislado por test.
    monkeypatch.setattr(router, "_shared_checkpointer", MemorySaver())
    monkeypatch.setattr(router, "GOVERNOR", None)  # cuotas LLM06 limpias en cada test
    from ai_agent_service.security.token_budget import MemoryCounterStore, TokenBudget

    monkeypatch.setattr(router, "TOKEN_BUDGET", TokenBudget(  # sin Redis en tests de API: contadores en memoria
        MemoryCounterStore(), user_tokens_per_day=10**9, global_tokens_per_day=10**9,
        global_tokens_per_minute=10**9, global_requests_per_day=10**9))
    service = AssistantService(**ports, checkpointer=router._shared_checkpointer)
    app.dependency_overrides[router._get_assistant_service] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ai") as c:
        yield c
    app.dependency_overrides.clear()
