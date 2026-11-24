from abc import ABC, abstractmethod
import uuid
from catalog_service.domain.entities import Product, Genre, Platform


class CatalogRepositoryPort(ABC):
    @abstractmethod
    async def get_all(self, skip: int = 0, limit: int = 50) -> list[Product]:
        ...

    @abstractmethod
    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        ...

    @abstractmethod
    async def update_stock(self, product_id: uuid.UUID, delta: int) -> bool:
        ...

    @abstractmethod
    async def create(self, product: Product) -> Product:
        ...


VideoGameRepository = CatalogRepositoryPort

