"""Listar el catálogo: "¿qué juegos tienen?" responde con el catálogo EN VIVO (Aurora vía catalog-service),
no con los 10 vecinos más cercanos del vector store."""

import json
import uuid

import pytest
from ai_agent_service.application.catalog_listing import (
    MAX_LISTED_GAMES,
    filter_listing,
    format_catalog_listing,
    is_catalog_listing_query,
)
from ai_agent_service.application.services import AssistantService
from ai_agent_service.domain.entities import Genre, VideoGame


def vg(title, platform="PS5", genres=("Acción",), price=39990, stock=5):
    return VideoGame(id=uuid.uuid4(), title=title, price_clp=price, stock=stock, platform=platform,
                     genres=[Genre(name=g) for g in genres])


@pytest.mark.parametrize("query", [
    "¿Qué juegos tienen?",
    "que juegos hay",
    "Qué juegos venden en la tienda?",
    "¿qué juegos de PS5 tienen?",
    "muéstrame el catálogo",
    "quiero ver el catalogo completo",
    "lista de juegos",
    "dame el listado de juegos disponibles",
    "¿cuáles son todos los juegos?",
    "juegos disponibles",
])
def test_listing_queries_are_detected(query):
    assert is_catalog_listing_query(query) is True


@pytest.mark.parametrize("query", [
    "recomiéndame un RPG",
    "quiero un juego de terror para jugar con amigos",
    "¿cuánto cuesta Zelda?",
    "hola",
    "¿Elden Ring tiene modo cooperativo?",
    "",
])
def test_recommendation_queries_are_not_listings(query):
    assert is_catalog_listing_query(query) is False


def test_filter_by_platform_alias():
    games = [vg("Spider-Man 2", "PS5"), vg("Halo Infinite", "Xbox Series"), vg("Mario Kart X", "Switch 2")]
    assert [g.title for g in filter_listing(games, "¿qué juegos de playstation tienen?")] == ["Spider-Man 2"]
    assert [g.title for g in filter_listing(games, "juegos de switch disponibles")] == ["Mario Kart X"]


def test_filter_by_genre_name_ignoring_accents():
    games = [vg("Gran Turismo 7", genres=("Carreras",)), vg("Starfield", genres=("Ciencia Ficción", "RPG"))]
    assert [g.title for g in filter_listing(games, "que juegos de ciencia ficcion hay")] == ["Starfield"]


def test_filter_without_matches_keeps_the_whole_catalog():
    games = [vg("Spider-Man 2"), vg("Halo Infinite", "Xbox Series")]
    assert filter_listing(games, "que juegos hay") == games


def test_listing_is_compact_and_flags_out_of_stock():
    text = format_catalog_listing([vg("Starfield", "Xbox Series", ("RPG",), 44990, 0)])
    assert text == "1. Starfield — Xbox Series — $44990 CLP — RPG — SIN STOCK"
    assert "Stock: 3" in format_catalog_listing([vg("Halo", stock=3)])


class ListingCatalog:
    def __init__(self, games):
        self.games, self.list_calls, self.verify_calls = games, [], 0

    async def list_products(self, limit):
        self.list_calls.append(limit)
        return self.games

    async def verify(self, games):
        self.verify_calls += 1
        return games


async def _stream(service, query):
    return [json.loads(c[len("data: "):]) async for c in service.chat_stream(query)]


async def test_listing_query_puts_the_whole_live_catalog_in_the_prompt(ports):
    games = [vg(f"Juego {i}") for i in range(1, 23)]
    catalog = ListingCatalog(games)
    events = await _stream(AssistantService(**ports, catalog_port=catalog), "¿Qué juegos tienen?")

    prompt = ports["llm_port"].prompts[-1]
    assert all(f"Juego {i} —" in prompt for i in range(1, 23))
    assert catalog.list_calls == [MAX_LISTED_GAMES]
    products = next(e for e in events if e["type"] == "products")["data"]
    assert len(products) == 10  # la UI recibe tarjetas acotadas; el modelo ve el catálogo completo


async def test_listing_by_platform_only_lists_that_platform(ports):
    catalog = ListingCatalog([vg("Spider-Man 2", "PS5"), vg("Halo Infinite", "Xbox Series")])
    await _stream(AssistantService(**ports, catalog_port=catalog), "¿qué juegos de PS5 tienen?")
    prompt = ports["llm_port"].prompts[-1]
    assert "Spider-Man 2 —" in prompt and "Halo Infinite" not in prompt


async def test_catalog_outage_falls_back_to_semantic_search(ports):
    catalog = ListingCatalog(None)  # list_products devuelve None: catálogo caído
    await _stream(AssistantService(**ports, catalog_port=catalog), "¿Qué juegos tienen?")
    assert "Hades II" in ports["llm_port"].prompts[-1]  # el resultado del vector store
    assert catalog.verify_calls == 1


async def test_recommendations_do_not_read_the_whole_catalog(ports):
    catalog = ListingCatalog([vg("Juego 1")])
    await _stream(AssistantService(**ports, catalog_port=catalog), "recomiéndame un roguelike")
    assert catalog.list_calls == []
