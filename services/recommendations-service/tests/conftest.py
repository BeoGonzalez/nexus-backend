import uuid

import httpx
import pytest

from recommendations_service.domain.entities import ProductRecommendation
from recommendations_service.domain.ports import RecommendationStorePort


def rec(title: str, score: float = 0.9) -> ProductRecommendation:
    return ProductRecommendation(product_id=uuid.uuid4(), title=title, price_clp=9990, score=score,
                                 recommendation_reason="test")


class FakeStore(RecommendationStorePort):
    def __init__(self) -> None:
        self.personal = {"alice": [rec("Hades II"), rec("Celeste"), rec("Hollow Knight")]}
        self.trending = [rec("Elden Ring"), rec("Balatro")]
        self.calls: list[tuple] = []

    async def get_recommendations_for_user(self, user_id: str, limit: int = 6):
        self.calls.append(("user", user_id, limit))
        return self.personal.get(user_id, self.trending)[:limit]

    async def get_trending_products(self, limit: int = 6):
        self.calls.append(("trending", limit))
        return self.trending[:limit]

    async def track_interaction(self, user_id, product_id, weight) -> None:
        self.calls.append(("track", user_id, product_id, weight))


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
async def client(store):
    from recommendations_service.application.services import RecommendationService
    from recommendations_service.main import app
    from recommendations_service.presentation.router import get_recommendation_service

    app.dependency_overrides[get_recommendation_service] = lambda: RecommendationService(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://recs") as c:
        yield c
    app.dependency_overrides.clear()
