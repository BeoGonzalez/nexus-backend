"""LLM07 Misinformation: precio y stock que ve el modelo salen del catálogo EN VIVO, no de metadatos viejos."""

import uuid

import httpx
import respx

from ai_agent_service.domain.entities import VideoGame
from ai_agent_service.infrastructure.catalog_client import CatalogVerifier

BASE = "http://catalog"


def game(**kw):
    return VideoGame(id=kw.pop("id", uuid.uuid4()), title=kw.pop("title", "Hades II"), price_clp=kw.pop("price", 9990),
                     stock=kw.pop("stock", 5), **kw)


def live(vg, price, stock):
    return {"id": str(vg.id), "title": vg.title, "description": "", "price_clp": price, "stock": stock,
            "image_url": None, "genres": []}


async def test_live_price_and_stock_replace_stale_vector_metadata():
    stale = game(price=9990, stock=5)
    with respx.mock(base_url=BASE) as mock:
        mock.get(f"/api/v1/catalog/products/{stale.id}").respond(json=live(stale, 14990, 0))
        [fresh] = await CatalogVerifier(BASE).verify([stale])
    assert fresh.price_clp == 14990 and fresh.stock == 0


async def test_products_deleted_from_the_catalog_are_not_recommended():
    kept, deleted = game(title="Celeste"), game(title="Juego retirado")
    with respx.mock(base_url=BASE) as mock:
        mock.get(f"/api/v1/catalog/products/{kept.id}").respond(json=live(kept, 9990, 3))
        mock.get(f"/api/v1/catalog/products/{deleted.id}").respond(404, json={"detail": "no existe"})
        result = await CatalogVerifier(BASE).verify([kept, deleted])
    assert [g.title for g in result] == ["Celeste"]


async def test_catalog_outage_keeps_results_but_never_raises():
    vg = game()
    with respx.mock(base_url=BASE) as mock:
        mock.get(f"/api/v1/catalog/products/{vg.id}").mock(side_effect=httpx.ConnectTimeout("caído"))
        result = await CatalogVerifier(BASE).verify([vg])
    assert result == [vg]


async def test_a_lying_catalog_response_for_another_id_is_ignored():
    vg, other = game(), game()
    with respx.mock(base_url=BASE) as mock:
        mock.get(f"/api/v1/catalog/products/{vg.id}").respond(json=live(other, 1, 999))
        [result] = await CatalogVerifier(BASE).verify([vg])
    assert result.price_clp == vg.price_clp  # la respuesta no corresponde al id pedido: no se usa


async def test_service_uses_verified_catalog_data_in_the_prompt(ports):
    from ai_agent_service.application.services import AssistantService

    class FakeCatalog:
        async def verify(self, games):
            return [VideoGame(id=g.id, title=g.title, description=g.description, price_clp=77777, stock=2,
                              genres=g.genres) for g in games]

    service = AssistantService(**ports, catalog_port=FakeCatalog())
    _ = [e async for e in service.chat_stream(query="algo de acción")]
    assert "77777" in ports["llm_port"].prompts[-1]
