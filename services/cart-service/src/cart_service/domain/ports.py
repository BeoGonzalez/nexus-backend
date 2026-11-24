from abc import ABC, abstractmethod
import uuid
from cart_service.domain.entities import Cart


class CartRepositoryPort(ABC):
    @abstractmethod
    async def get_by_user_id(self, user_id: str) -> Cart:
        ...

    @abstractmethod
    async def save(self, cart: Cart) -> Cart:
        ...

    @abstractmethod
    async def clear(self, user_id: str) -> None:
        ...


class CatalogClientPort(ABC):
    @abstractmethod
    async def get_product_details(self, product_id: uuid.UUID) -> dict | None:
        ...

