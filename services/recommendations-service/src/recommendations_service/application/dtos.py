import uuid
from pydantic import BaseModel


class RecommendationResponse(BaseModel):
    product_id: uuid.UUID
    title: str
    price_clp: int
    score: float
    recommendation_reason: str
    image_url: str | None = None

