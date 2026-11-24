import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from catalog_service.domain.entities import Genre, Platform, Product
from catalog_service.domain.ports import CatalogRepositoryPort
from catalog_service.infrastructure.models import GenreModel, PlatformModel, ProductModel


class PostgresCatalogRepository(CatalogRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(model: ProductModel) -> Product:
        return Product(
            id=model.id,
            title=model.title,
            description=model.description,
            price_clp=model.price_clp,
            stock=model.stock,
            image_url=model.image_url,
            platform=Platform(id=model.platform.id, name=model.platform.name) if model.platform else None,
            genres=[Genre(id=g.id, name=g.name) for g in model.genres],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def get_all(self, skip: int = 0, limit: int = 50) -> list[Product]:
        stmt = select(ProductModel).offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_domain(m) for m in result.scalars().all()]

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        stmt = select(ProductModel).where(ProductModel.id == product_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def update_stock(self, product_id: uuid.UUID, delta: int) -> bool:
        stmt = (
            update(ProductModel)
            .where(ProductModel.id == product_id, (ProductModel.stock + delta) >= 0)
            .values(stock=ProductModel.stock + delta)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return (result.rowcount or 0) > 0

    async def create(self, product: Product) -> Product:
        model = ProductModel(
            id=product.id,
            title=product.title,
            description=product.description,
            price_clp=product.price_clp,
            stock=product.stock,
            image_url=product.image_url,
        )
        self._session.add(model)
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_domain(model)

