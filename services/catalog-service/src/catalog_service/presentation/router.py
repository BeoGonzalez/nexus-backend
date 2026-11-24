import uuid
from collections.abc import AsyncGenerator
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from catalog_service.application.dtos import (
    CreateProductRequest,
    GenreResponse,
    PlatformResponse,
    ProductResponse,
    UpdateStockRequest,
)
from catalog_service.application.services import CatalogService
from catalog_service.config import get_settings
from catalog_service.domain.entities import Product
from catalog_service.infrastructure.repositories import PostgresCatalogRepository
from nexus_core.infrastructure.database import (
    DatabaseConnectionConfig,
    create_db_engine,
    create_session_factory,
)
from nexus_events.publisher import EventPublisher
from nexus_security.permissions import require_role

router = APIRouter(prefix="/api/v1/catalog", tags=["Catalog Service"])
settings = get_settings()

_engine = create_db_engine(DatabaseConnectionConfig(database_url=settings.DATABASE_URL))
_session_factory = create_session_factory(_engine)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with _session_factory() as session:
        yield session


def get_catalog_service(session: AsyncSession = Depends(get_db_session)) -> CatalogService:
    repo = PostgresCatalogRepository(session)
    publisher = EventPublisher(settings.EVENTS_TOPIC_ARN, region=settings.AWS_REGION)
    return CatalogService(repo=repo, publisher=publisher)


def _to_response(p: Product) -> ProductResponse:
    return ProductResponse(
        id=p.id,
        title=p.title,
        description=p.description,
        price_clp=p.price_clp,
        stock=p.stock,
        image_url=p.image_url,
        platform=PlatformResponse(id=p.platform.id, name=p.platform.name) if p.platform else None,
        genres=[GenreResponse(id=g.id, name=g.name) for g in p.genres],
    )


@router.get("/products", response_model=list[ProductResponse])
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    service: CatalogService = Depends(get_catalog_service),
) -> list[ProductResponse]:
    products = await service.list_products(skip=skip, limit=limit)
    return [_to_response(p) for p in products]


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    service: CatalogService = Depends(get_catalog_service),
) -> ProductResponse:
    product = await service.get_product(product_id)
    return _to_response(product)


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    request: CreateProductRequest,
    service: CatalogService = Depends(get_catalog_service),
    _admin=Depends(require_role("admin")),
) -> ProductResponse:
    product = await service.create_product(request)
    return _to_response(product)


@router.patch("/products/{product_id}/stock")
async def update_stock(
    product_id: uuid.UUID,
    request: UpdateStockRequest,
    service: CatalogService = Depends(get_catalog_service),
    _admin=Depends(require_role("admin")),
) -> dict:
    dummy_order = uuid.uuid4()
    if request.delta < 0:
        success = await service.reserve_stock(dummy_order, product_id, -request.delta)
    else:
        success = await service.release_stock(dummy_order, product_id, request.delta)
    return {"product_id": str(product_id), "updated": success}


@router.get("/health")
async def health_check() -> dict:
    return {"status": "healthy", "service": "catalog-service"}

