import json
import logging
import uuid
import redis.asyncio as redis
from recommendations_service.domain.entities import ProductRecommendation
from recommendations_service.domain.ports import RecommendationStorePort

logger = logging.getLogger("recommendations.store")


class RedisRecommendationStore(RecommendationStorePort):
    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def get_recommendations_for_user(self, user_id: str, limit: int = 6) -> list[ProductRecommendation]:
        # En una arquitectura real, lee embeddings de afinidad y busca top-k
        raw = await self._redis.get(f"recommendations:{user_id}")
        if raw:
            items = json.loads(raw)
            return [
                ProductRecommendation(
                    product_id=uuid.UUID(i["product_id"]),
                    title=i["title"],
                    price_clp=i["price_clp"],
                    score=i.get("score", 1.0),
                    recommendation_reason=i.get("reason", "Basado en tus preferencias"),
                    image_url=i.get("image_url"),
                )
                for i in items[:limit]
            ]
        return await self.get_trending_products(limit=limit)

    async def get_trending_products(self, limit: int = 6) -> list[ProductRecommendation]:
        raw = await self._redis.get("recommendations:trending")
        if raw:
            items = json.loads(raw)
            return [
                ProductRecommendation(
                    product_id=uuid.UUID(i["product_id"]),
                    title=i["title"],
                    price_clp=i["price_clp"],
                    score=i.get("score", 1.0),
                    recommendation_reason="Más populares de la semana",
                    image_url=i.get("image_url"),
                )
                for i in items[:limit]
            ]
        # Fallback sintético para demo
        return [
            ProductRecommendation(
                product_id=uuid.uuid4(),
                title="Cyberpunk 2077: Phantom Liberty",
                price_clp=29990,
                score=0.98,
                recommendation_reason="Top Ventas en PC Gaming",
            ),
            ProductRecommendation(
                product_id=uuid.uuid4(),
                title="Elden Ring: Shadow of the Erdtree",
                price_clp=34990,
                score=0.96,
                recommendation_reason="Juego del Año Recomendado",
            ),
        ][:limit]

    async def track_interaction(self, user_id: str, product_id: uuid.UUID, weight: float) -> None:
        key = f"affinity:{user_id}"
        await self._redis.zincrby(key, weight, str(product_id))
        await self._redis.expire(key, 60 * 60 * 24 * 30)

