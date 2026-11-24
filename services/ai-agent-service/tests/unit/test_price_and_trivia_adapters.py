import httpx
import pytest
import respx

from ai_agent_service.infrastructure import wikipedia as wiki_module
from ai_agent_service.infrastructure.cheapshark_adapter import CheapSharkPriceAdapter
from ai_agent_service.infrastructure.wikipedia import WikipediaAdapter

CS = "https://www.cheapshark.com/api/1.0"


def _mock_cheapshark(mock, deals):
    mock.get(f"{CS}/stores").respond(200, json=[])
    mock.get(f"{CS}/games", params={"title": "Hades II", "limit": "3"}).respond(
        200, json=[{"gameID": "42", "external": "Hades II"}])
    mock.get(f"{CS}/games", params={"id": "42"}).respond(200, json={"info": {"title": "Hades II"}, "deals": deals})


@pytest.fixture
def cheapshark():
    return CheapSharkPriceAdapter(enabled=True, usd_clp_rate=1000.0)


async def test_nexus_cheaper_than_cheapest_external_store(cheapshark):
    with respx.mock as mock:
        _mock_cheapshark(mock, [
            {"storeID": "1", "price": "29.99", "retailPrice": "29.99", "savings": "0"},
            {"storeID": "25", "price": "24.99", "retailPrice": "29.99", "savings": "16"},
        ])
        result = await cheapshark.compare_price("Hades II", 19990)
    assert result["has_data"] is True
    assert result["savings_clp"] == 24990 - 19990
    assert "MÁS BARATO que en Epic Games Store" in result["comparison_summary"]


async def test_nexus_more_expensive_reports_no_savings(cheapshark):
    with respx.mock as mock:
        _mock_cheapshark(mock, [{"storeID": "1", "price": "9.99", "retailPrice": "29.99", "savings": "66"}])
        result = await cheapshark.compare_price("Hades II", 19990)
    assert result["savings_clp"] == 0
    assert "oferta especial a $9.990 CLP" in result["comparison_summary"]


async def test_unknown_game_has_no_data(cheapshark):
    with respx.mock as mock:
        mock.get(f"{CS}/stores").respond(200, json=[])
        mock.get(f"{CS}/games").respond(200, json=[])
        assert (await cheapshark.compare_price("Juego Inexistente", 1000))["has_data"] is False


async def test_network_failure_has_no_data(cheapshark):
    with respx.mock as mock:
        mock.get(url__startswith=CS).mock(side_effect=httpx.ConnectTimeout("t"))
        assert (await cheapshark.compare_price("Hades II", 1000))["has_data"] is False


async def test_disabled_adapter_makes_no_requests():
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(url__startswith=CS)
        result = await CheapSharkPriceAdapter(enabled=False).compare_price("Hades II", 1000)
    assert result["has_data"] is False
    assert not route.called


class _FakeWikiLib:
    def __init__(self, fail=False):
        self.fail, self.queries = fail, []

    def set_lang(self, lang):
        self.lang = lang

    def search(self, query, results=1):
        self.queries.append(query)
        if self.fail:
            raise ConnectionError("sin red")
        return ["Hades II"]

    def summary(self, title, sentences=3):
        return "Hades II es un videojuego roguelike desarrollado por Supergiant Games. " * 10


@pytest.fixture
def offline_wikipedia(monkeypatch):
    lib = _FakeWikiLib()
    monkeypatch.setattr(wiki_module, "WikipediaAPIWrapper", None)
    monkeypatch.setattr(wiki_module, "wikipedia", lib)
    return lib


async def test_trivia_appends_videojuego_and_truncates(offline_wikipedia):
    text = await WikipediaAdapter(lang="es", top_k_results=1, doc_content_chars_max=50).fetch_trivia("Hades II")
    assert offline_wikipedia.queries == ["Hades II videojuego"]
    assert len(text) <= 50 and text.startswith("Hades II es un videojuego")


async def test_trivia_failure_degrades_gracefully(offline_wikipedia):
    offline_wikipedia.fail = True
    assert await WikipediaAdapter().fetch_trivia("Hades II") == "Sin datos externos."


async def test_empty_topic_returns_no_data(offline_wikipedia):
    assert await WikipediaAdapter().fetch_trivia("") == "Sin datos externos."
    assert offline_wikipedia.queries == []
