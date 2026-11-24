import uuid

import httpx
import respx

from cart_service.infrastructure.catalog_client import HttpCatalogClient

PID = uuid.uuid4()
URL = f"http://catalog.test/api/v1/catalog/products/{PID}"


@respx.mock
async def test_returns_product_payload_on_200():
    respx.get(URL).respond(200, json={"title": "Hades II", "stock": 3})
    assert await HttpCatalogClient().get_product_details(PID) == {"title": "Hades II", "stock": 3}


@respx.mock
async def test_returns_none_on_404():
    respx.get(URL).respond(404)
    assert await HttpCatalogClient().get_product_details(PID) is None


@respx.mock
async def test_returns_none_when_catalog_unreachable():
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("timeout"))
    assert await HttpCatalogClient().get_product_details(PID) is None
