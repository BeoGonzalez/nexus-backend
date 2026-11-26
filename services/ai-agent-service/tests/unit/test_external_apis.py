"""APIs externas del asistente (Tavily, CheapShark, Wikipedia): visibles en Grafana, sin fallos silenciosos y en paralelo.

Antes cada fallo se registraba en DEBUG (invisible en producción) y devolvía un texto genérico, y las tres búsquedas
iban una tras otra sumando su latencia a cada chat (que además choca con el límite de 29 s de API Gateway).
"""

import asyncio
import json
import logging

import httpx
import pytest
import respx
from ai_agent_service.infrastructure import wikipedia as wiki_module
from ai_agent_service.infrastructure.cheapshark_adapter import CheapSharkPriceAdapter
from ai_agent_service.infrastructure.llm_metrics import (
    EXTERNAL_OUTCOMES,
    EXTERNAL_SOURCES,
    LLMMetrics,
)
from ai_agent_service.infrastructure.tavily_adapter import TavilyNewsAdapter
from ai_agent_service.infrastructure.wikipedia import WikipediaAdapter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

TAVILY = "https://api.tavily.com/search"
CS = "https://www.cheapshark.com/api/1.0"
SECRET_KEY = "tvly-clave-secreta-de-prueba"


@pytest.fixture
def reader():
    return InMemoryMetricReader()


@pytest.fixture
def metrics(reader):
    return LLMMetrics(MeterProvider(metric_readers=[reader]))


def calls(reader):
    """{(source, outcome): valor} de nexus_llm_external_calls."""
    out = {}
    data = reader.get_metrics_data()
    for rm in data.resource_metrics if data else []:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == "nexus_llm_external_calls":
                    for p in m.data.data_points:
                        out[(p.attributes["source"], p.attributes["outcome"])] = p.value
    return out


def test_every_source_and_outcome_starts_at_zero_so_the_first_call_is_visible(metrics, reader):
    assert calls(reader) == {(s, o): 0 for s in EXTERNAL_SOURCES for o in EXTERNAL_OUTCOMES}


def test_external_call_records_outcome_and_duration(metrics, reader):
    metrics.external_call(source="tavily", outcome="timeout", seconds=6.0)
    assert calls(reader)[("tavily", "timeout")] == 1


# ---------------------------------------------------------------------------------------------- Tavily

def test_tavily_waits_up_to_6_seconds():
    assert TavilyNewsAdapter(api_key="k")._timeout == 6.0


@pytest.mark.parametrize("respond,outcome", [
    (lambda r: r.respond(200, json={"results": [{"title": "Parche 1.1", "content": "Notas", "url": "https://x"}]}), "ok"),
    (lambda r: r.respond(200, json={"results": []}), "empty"),
    (lambda r: r.mock(side_effect=httpx.ReadTimeout("lento")), "timeout"),
    (lambda r: r.respond(500, text="boom"), "error"),
])
async def test_tavily_reports_each_outcome(metrics, reader, respond, outcome):
    with respx.mock as mock:
        respond(mock.post(TAVILY))
        await TavilyNewsAdapter(api_key=SECRET_KEY, metrics=metrics).fetch_news("Hades II")
    assert calls(reader)[("tavily", outcome)] == 1


async def test_tavily_failures_are_warnings_without_the_key_or_the_query(metrics, caplog):
    with respx.mock as mock, caplog.at_level(logging.INFO):
        mock.post(TAVILY).mock(side_effect=httpx.ReadTimeout("lento"))
        await TavilyNewsAdapter(api_key=SECRET_KEY, metrics=metrics).fetch_news("busco algo muy personal")
    [record] = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert "tavily" in record.getMessage().lower() and "timeout" in record.getMessage().lower()
    assert SECRET_KEY not in caplog.text and "muy personal" not in caplog.text


async def test_tavily_without_key_does_not_count_a_call(metrics, reader):
    await TavilyNewsAdapter(api_key="", metrics=metrics).fetch_news("Hades II")
    assert sum(calls(reader).values()) == 0


# ------------------------------------------------------------------------------------------- CheapShark

def _cheapshark(mock, found=True):
    mock.get(f"{CS}/stores").respond(200, json=[])
    mock.get(f"{CS}/games", params={"title": "Hades II", "limit": "3"}).respond(
        200, json=[{"gameID": "42", "external": "Hades II"}] if found else [])
    mock.get(f"{CS}/games", params={"id": "42"}).respond(200, json={"info": {"title": "Hades II"}, "deals": [
        {"storeID": "1", "price": "29.99", "retailPrice": "29.99", "savings": "0"}]})


@pytest.mark.parametrize("found,outcome", [(True, "ok"), (False, "empty")])
async def test_cheapshark_reports_ok_and_empty(metrics, reader, found, outcome):
    with respx.mock(assert_all_called=False) as mock:
        _cheapshark(mock, found=found)
        await CheapSharkPriceAdapter(enabled=True, usd_clp_rate=1000.0, metrics=metrics).compare_price("Hades II", 19990)
    assert calls(reader)[("cheapshark", outcome)] == 1


async def test_cheapshark_network_failure_is_a_warning_and_an_error(metrics, reader, caplog):
    with respx.mock as mock, caplog.at_level(logging.INFO):
        mock.get(f"{CS}/stores").respond(200, json=[])
        mock.get(f"{CS}/games").mock(side_effect=httpx.ConnectError("sin red"))
        await CheapSharkPriceAdapter(enabled=True, usd_clp_rate=1000.0, metrics=metrics).compare_price("Hades II", 19990)
    assert calls(reader)[("cheapshark", "error")] == 1
    assert any(r.levelno == logging.WARNING and "cheapshark" in r.getMessage().lower() for r in caplog.records)


# -------------------------------------------------------------------------------------------- Wikipedia

class FakeWiki:
    def __init__(self, result=None, fail=False):
        self.result, self.fail = result, fail

    def run(self, query):
        if self.fail:
            raise ConnectionError("sin red")
        return self.result


@pytest.mark.parametrize("wiki,outcome", [(FakeWiki("Hades II es un roguelike."), "ok"), (FakeWiki(""), "empty"),
                                          (FakeWiki(fail=True), "error")])
async def test_wikipedia_reports_each_outcome(metrics, reader, monkeypatch, wiki, outcome):
    monkeypatch.setattr(wiki_module, "wikipedia", None)
    adapter = WikipediaAdapter(metrics=metrics)
    adapter._wiki = wiki
    await adapter.fetch_trivia("Hades II")
    assert calls(reader)[("wikipedia", outcome)] == 1


# ------------------------------------------------------------------------------- en paralelo, no en serie

class Rendezvous:
    """Cada búsqueda espera a que arranquen las tres: si el servicio las hace en serie, ninguna llega a responder."""

    def __init__(self, n=3):
        self.started, self.n, self.ready = 0, n, asyncio.Event()

    async def wait(self):
        self.started += 1
        if self.started == self.n:
            self.ready.set()
        await asyncio.wait_for(self.ready.wait(), timeout=1.0)


async def test_trivia_news_and_prices_run_concurrently(ports):
    from ai_agent_service.application.services import AssistantService

    meet = Rendezvous()

    class Trivia:
        async def fetch_trivia(self, topic):
            await meet.wait()
            return f"Trivia de {topic}"

    class News:
        async def fetch_news(self, query):
            await meet.wait()
            return f"Noticia sobre {query}"

    class Prices:
        async def compare_price(self, title, price):
            await meet.wait()
            return {"has_data": True, "comparison_summary": f"Steam vende {title} más caro"}

    ports.update(external_knowledge_port=Trivia(), gaming_news_port=News(), price_comparison_port=Prices())
    _ = [json.loads(c[6:]) async for c in AssistantService(**ports).chat_stream("quiero un roguelike")]
    prompt = ports["llm_port"].prompts[-1]
    assert "Trivia de Hades II" in prompt and "Noticia sobre Hades II" in prompt and "Steam vende Hades II" in prompt


class FakeWikipediaModule:
    def __init__(self):
        self.user_agent = None

    def set_user_agent(self, ua):
        self.user_agent = ua


def test_wikipedia_identifies_itself_or_wikimedia_answers_429_after_two_requests(monkeypatch):
    """Con el User-Agent genérico de la librería, Wikimedia responde HTTP 429 desde la 3.ª consulta seguida."""
    fake = FakeWikipediaModule()
    monkeypatch.setattr(wiki_module, "wikipedia", fake)
    WikipediaAdapter()
    assert fake.user_agent and fake.user_agent.startswith("NexusDigitalStore/")
    assert "goldsmith" not in fake.user_agent
