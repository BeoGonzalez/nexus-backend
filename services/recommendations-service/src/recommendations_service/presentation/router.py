from fastapi import APIRouter, Depends, Query
import redis.asyncio as redis

from nexus_security.dependencies import get_current_user
from nexus_security.jwt import TokenPayload
from recommendations_service.application.dtos import RecommendationResponse
from recommendations_service.application.services import RecommendationService
from recommendations_service.config import get_settings
from recommendations_service.domain.entities import ProductRecommendation
from recommendations_service.infrastructure.redis_store import RedisRecommendationStore

router = APIRouter(prefix="/api/v1/recommendations", tags=["Recommendations Service"])
settings = get_settings()

_redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)


def get_recommendation_service() -> RecommendationService:
    store = RedisRecommendationStore(_redis_client)
    return RecommendationService(store)


def _to_response(rec: ProductRecommendation) -> RecommendationResponse:
    return RecommendationResponse(
        product_id=rec.product_id,
        title=rec.title,
        price_clp=rec.price_clp,
        score=rec.score,
        recommendation_reason=rec.recommendation_reason,
        image_url=rec.image_url,
    )


@router.get("/for-you", response_model=list[RecommendationResponse])
async def get_for_you(
    limit: int = Query(6, ge=1, le=20),
    current_user: TokenPayload = Depends(get_current_user),
    service: RecommendationService = Depends(get_recommendation_service),
) -> list[RecommendationResponse]:
    items = await service.get_for_user(current_user.sub, limit=limit)
    return [_to_response(i) for i in items]


@router.get("/trending", response_model=list[RecommendationResponse])
async def get_trending(
    limit: int = Query(6, ge=1, le=20),
    service: RecommendationService = Depends(get_recommendation_service),
) -> list[RecommendationResponse]:
    items = await service.get_trending(limit=limit)
    return [_to_response(i) for i in items]


@router.get("/health")
async def health_check() -> dict:
    return {"status": "healthy", "service": "recommendations-service"}

