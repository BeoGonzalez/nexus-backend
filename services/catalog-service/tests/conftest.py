import uuid

import httpx
import pytest

from catalog_service.domain.entities import Product
from catalog_service.domain.ports import CatalogRepositoryPort
from nexus_testkit import FakePublisher


class InMemoryCatalogRepository(CatalogRepositoryPort):
    def __init__(self, products: list[Product] | None = None) -> None:
        self.products: dict[uuid.UUID, Product] = {p.id: p for p in products or []}

    async def get_all(self, skip: int = 0, limit: int = 50) -> list[Product]:
        return list(self.products.values())[skip: skip + limit]

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        return self.products.get(product_id)

    async def update_stock(self, product_id: uuid.UUID, delta: int) -> bool:
        product = self.products.get(product_id)
        if not product or product.stock + delta < 0:
            return False
        product.stock += delta
        return True

    async def create(self, product: Product) -> Product:
        self.products[product.id] = product
        return product


def make_product(title="Hades II", price=19990, stock=5) -> Product:
    return Product(title=title, description="Roguelike", price_clp=price, stock=stock)


@pytest.fixture
def repo():
    return InMemoryCatalogRepository([make_product()])


@pytest.fixture
def publisher():
    return FakePublisher()


@pytest.fixture
async def client(repo, publisher):
    from catalog_service.application.services import CatalogService
    from catalog_service.main import app
    from catalog_service.presentation.router import get_catalog_service

    app.dependency_overrides[get_catalog_service] = lambda: CatalogService(repo=repo, publisher=publisher)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://catalog") as c:
        yield c
    app.dependency_overrides.clear()
