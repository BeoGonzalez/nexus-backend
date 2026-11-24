import uuid
from pydantic import BaseModel, Field


class GenreResponse(BaseModel):
    id: uuid.UUID
    name: str


class PlatformResponse(BaseModel):
    id: uuid.UUID
    name: str


class ProductResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    price_clp: int
    stock: int
    image_url: str | None = None
    platform: PlatformResponse | None = None
    genres: list[GenreResponse] = []


class CreateProductRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    description: str = Field(..., max_length=5000)
    price_clp: int = Field(..., gt=0, le=100_000_000)
    stock: int = Field(..., ge=0, le=1_000_000)
    # Solo https (bloquea javascript:/data:/http: → XSS almacenado o contenido mixto) y longitud acotada.
    image_url: str | None = Field(default=None, max_length=2048, pattern=r"^https://[^\s<>\"']+$")
    platform_name: str | None = Field(default=None, max_length=100)
    genre_names: list[str] = Field(default_factory=list, max_length=20)


class UpdateStockRequest(BaseModel):
    delta: int = Field(..., ge=-100_000, le=100_000, description="Cantidad a incrementar (+) o decrementar (-)")

