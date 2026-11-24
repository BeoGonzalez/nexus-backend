from abc import ABC, abstractmethod
import uuid
from recommendations_service.domain.entities import ProductRecommendation


class RecommendationStorePort(ABC):
    @abstractmethod
    async def get_recommendations_for_user(self, user_id: str, limit: int = 6) -> list[ProductRecommendation]:
        ...

    @abstractmethod
    async def get_trending_products(self, limit: int = 6) -> list[ProductRecommendation]:
        ...

    @abstractmethod
    async def track_interaction(self, user_id: str, product_id: uuid.UUID, weight: float) -> None:
        ...

