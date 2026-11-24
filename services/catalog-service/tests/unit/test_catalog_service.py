import uuid

import pytest

from catalog_service.application.dtos import CreateProductRequest
from catalog_service.application.services import CatalogService
from nexus_core.domain.exceptions import ResourceNotFoundException
from nexus_events.schemas.catalog import StockReleasedEvent, StockReservationFailedEvent, StockReservedEvent


def _only_product(repo):
    return next(iter(repo.products.values()))


async def test_get_missing_product_raises_not_found(repo):
    with pytest.raises(ResourceNotFoundException):
        await CatalogService(repo).get_product(uuid.uuid4())


async def test_create_product_persists_requested_fields(repo):
    created = await CatalogService(repo).create_product(
        CreateProductRequest(title="Celeste", description="Plataformas", price_clp=9990, stock=3)
    )
    stored = repo.products[created.id]
    assert (stored.title, stored.price_clp, stored.stock) == ("Celeste", 9990, 3)


async def test_successful_reservation_decrements_stock_and_emits_reserved(repo, publisher):
    product, order_id = _only_product(repo), uuid.uuid4()
    assert await CatalogService(repo, publisher).reserve_stock(order_id, product.id, 2) is True
    assert product.stock == 3
    [(key, event)] = publisher.published
    assert key == "catalog.stock_reserved"
    assert isinstance(event, StockReservedEvent)
    assert (event.order_id, event.product_id, event.quantity) == (order_id, product.id, 2)


async def test_reservation_beyond_stock_fails_and_emits_failure(repo, publisher):
    product = _only_product(repo)
    assert await CatalogService(repo, publisher).reserve_stock(uuid.uuid4(), product.id, 6) is False
    assert product.stock == 5
    [(key, event)] = publisher.published
    assert key == "catalog.stock_reservation_failed"
    assert isinstance(event, StockReservationFailedEvent)


async def test_release_returns_stock_and_emits_released(repo, publisher):
    product = _only_product(repo)
    assert await CatalogService(repo, publisher).release_stock(uuid.uuid4(), product.id, 4) is True
    assert product.stock == 9
    assert isinstance(publisher.published[0][1], StockReleasedEvent)


async def test_release_of_unknown_product_emits_nothing(repo, publisher):
    assert await CatalogService(repo, publisher).release_stock(uuid.uuid4(), uuid.uuid4(), 1) is False
    assert publisher.published == []


async def test_works_without_publisher(repo):
    assert await CatalogService(repo, None).reserve_stock(uuid.uuid4(), _only_product(repo).id, 1) is True


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(document.cookie)", "data:text/html,<script>alert(1)</script>", "http://insecure.example/x.png",
     "https://" + "a" * 2100 + ".com/x.png"],
)
def test_product_image_url_must_be_https_and_bounded(url):
    from pydantic import ValidationError

    from catalog_service.application.dtos import CreateProductRequest

    with pytest.raises(ValidationError):
        CreateProductRequest(title="Hades II", description="x", price_clp=1, stock=1, image_url=url)


def test_product_https_image_url_is_accepted():
    from catalog_service.application.dtos import CreateProductRequest

    req = CreateProductRequest(title="Hades II", description="x", price_clp=1, stock=1,
                               image_url="https://images.unsplash.com/photo.png")
    assert req.image_url.startswith("https://")
