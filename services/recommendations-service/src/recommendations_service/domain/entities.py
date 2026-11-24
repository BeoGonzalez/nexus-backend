from dataclasses import dataclass
import uuid


@dataclass
class ProductRecommendation:
    product_id: uuid.UUID
    title: str
    price_clp: int
    score: float
    recommendation_reason: str
    image_url: str | None = None

