import math

import httpx
import pytest
import respx

from ai_agent_service.infrastructure.embeddings import _FallbackEmbedder
from ai_agent_service.infrastructure.laya_adapter import LayaDecisionAdapter
from ai_agent_service.infrastructure.tavily_adapter import TavilyNewsAdapter

TAVILY = "https://api.tavily.com/search"


@pytest.mark.parametrize("query,intent", [
    ("envíame el mail a ana@b.cl con la oferta", "send_email"),
    ("hola", "greeting"),
    ("hola, busco un rpg largo de mundo abierto para el verano", "recommendation"),
    ("cuanto cuesta elden ring", "stock_price"),
    ("quiero un reembolso de mi pedido", "support"),
    ("algo de terror cooperativo", "recommendation"),
])
def test_heuristic_intent_classification(query, intent):
    assert LayaDecisionAdapter()._heuristic_classify(query) == intent


async def test_decision_extracts_recipient_and_urgency():
    metrics = await LayaDecisionAdapter().evaluate_decision("manda el correo a ana.p@b.cl por favor")
    assert (metrics["intent"], metrics["recipient_email"], metrics["urgency"]) == ("send_email", "ana.p@b.cl", 2)


async def test_empty_query_uses_fallback_intent():
    assert await LayaDecisionAdapter(fallback_intent="support").classify_intent("") == "support"


def test_fallback_embedder_is_deterministic_normalized_and_384_dims():
    e = _FallbackEmbedder()
    a, b, c = e.embed_query("hades"), e.embed_query("hades"), e.embed_query("celeste")
    assert len(a) == 384 and a == b and a != c
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-9)


async def test_tavily_without_api_key_makes_no_request():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(TAVILY)
        assert "API Key no configurada" in await TavilyNewsAdapter(api_key="").fetch_news("Hades II")
        assert not route.called


@respx.mock
async def test_tavily_formats_answer_and_results():
    respx.post(TAVILY).respond(200, json={"answer": " Nuevo parche ", "results": [
        {"title": "Hades II 1.0", "content": "x" * 200, "url": "https://n.example/1"}]})
    text = await TavilyNewsAdapter(api_key="k", max_results=3).fetch_news("Hades II")
    assert text.splitlines()[0] == "Resumen de noticias: Nuevo parche"
    assert text.splitlines()[1] == f"1. Hades II 1.0: {'x' * 160}... (https://n.example/1)"


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.ConnectTimeout("t")])
async def test_tavily_errors_degrade_to_message(response):
    with respx.mock as mock:
        route = mock.post(TAVILY)
        if isinstance(response, Exception):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)
        text = await TavilyNewsAdapter(api_key="k").fetch_news("Hades II")
    assert text.startswith("Sin noticias")
