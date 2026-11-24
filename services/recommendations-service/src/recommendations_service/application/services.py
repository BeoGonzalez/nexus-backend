from recommendations_service.domain.entities import ProductRecommendation
from recommendations_service.domain.ports import RecommendationStorePort


class RecommendationService:
    def __init__(self, store: RecommendationStorePort) -> None:
        self._store = store

    async def get_for_user(self, user_id: str, limit: int = 6) -> list[ProductRecommendation]:
        return await self._store.get_recommendations_for_user(user_id, limit=limit)

    async def get_trending(self, limit: int = 6) -> list[ProductRecommendation]:
        return await self._store.get_trending_products(limit=limit)

