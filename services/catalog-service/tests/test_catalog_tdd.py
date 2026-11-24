import uuid
import pytest
from catalog_service.application.dtos import CreateProductRequest
from catalog_service.application.services import CatalogService
from catalog_service.domain.entities import Product
from catalog_service.domain.ports import CatalogRepositoryPort


class InMemoryCatalogRepository(CatalogRepositoryPort):
    def __init__(self) -> None:
        self.products: dict[uuid.UUID, Product] = {}

    async def get_all(self, skip: int = 0, limit: int = 50) -> list[Product]:
        return list(self.products.values())[skip : skip + limit]

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        return self.products.get(product_id)

    async def update_stock(self, product_id: uuid.UUID, delta: int) -> bool:
        prod = self.products.get(product_id)
        if not prod:
            return False
        if prod.stock + delta < 0:
            return False
        prod.stock += delta
        return True

    async def create(self, product: Product) -> Product:
        self.products[product.id] = product
        return product


@pytest.mark.asyncio
async def test_catalog_create_and_get_product():
    repo = InMemoryCatalogRepository()
    service = CatalogService(repo)

    req = CreateProductRequest(
        title="Half-Life: Alyx",
        description="VR Masterpiece",
        price_clp=24990,
        stock=10,
    )
    product = await service.create_product(req)
    assert product.id is not None
    assert product.title == "Half-Life: Alyx"
    assert product.stock == 10

    retrieved = await service.get_product(product.id)
    assert retrieved.id == product.id


@pytest.mark.asyncio
async def test_catalog_reserve_and_release_stock():
    repo = InMemoryCatalogRepository()
    service = CatalogService(repo)

    prod = await service.create_product(
        CreateProductRequest(
            title="Doom Eternal",
            description="FPS",
            price_clp=19990,
            stock=5,
        )
    )

    # 1. Reserva exitosa
    order_id = uuid.uuid4()
    res1 = await service.reserve_stock(order_id, prod.id, 3)
    assert res1 is True
    updated = await service.get_product(prod.id)
    assert updated.stock == 2

    # 2. Intento de reservar más del disponible (falla)
    res2 = await service.reserve_stock(order_id, prod.id, 5)
    assert res2 is False
    assert (await service.get_product(prod.id)).stock == 2

    # 3. Liberación de stock por cancelación / rollback
    res3 = await service.release_stock(order_id, prod.id, 3)
    assert res3 is True
    assert (await service.get_product(prod.id)).stock == 5

