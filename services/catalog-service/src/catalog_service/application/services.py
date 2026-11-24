import uuid
from catalog_service.application.dtos import CreateProductRequest
from catalog_service.domain.entities import Product
from catalog_service.domain.ports import CatalogRepositoryPort
from nexus_core.domain.exceptions import BusinessRuleViolationException, ResourceNotFoundException
from nexus_events.publisher import EventPublisher
from nexus_events.schemas.catalog import StockReleasedEvent, StockReservationFailedEvent, StockReservedEvent


class CatalogService:
    def __init__(self, repo: CatalogRepositoryPort, publisher: EventPublisher | None = None) -> None:
        self._repo = repo
        self._publisher = publisher

    async def list_products(self, skip: int = 0, limit: int = 50) -> list[Product]:
        return await self._repo.get_all(skip=skip, limit=limit)

    async def get_product(self, product_id: uuid.UUID) -> Product:
        prod = await self._repo.get_by_id(product_id)
        if not prod:
            raise ResourceNotFoundException(f"Producto {product_id} no encontrado.")
        return prod

    async def create_product(self, request: CreateProductRequest) -> Product:
        product = Product(
            title=request.title,
            description=request.description,
            price_clp=request.price_clp,
            stock=request.stock,
            image_url=request.image_url,
        )
        return await self._repo.create(product)

    async def reserve_stock(self, order_id: uuid.UUID, product_id: uuid.UUID, quantity: int) -> bool:
        success = await self._repo.update_stock(product_id, -quantity)
        if self._publisher:
            if success:
                event = StockReservedEvent(order_id=order_id, product_id=product_id, quantity=quantity)
                await self._publisher.publish("catalog.stock_reserved", event)
            else:
                fail_event = StockReservationFailedEvent(order_id=order_id, product_id=product_id, reason="Stock insuficiente")
                await self._publisher.publish("catalog.stock_reservation_failed", fail_event)
        return success

    async def release_stock(self, order_id: uuid.UUID, product_id: uuid.UUID, quantity: int) -> bool:
        success = await self._repo.update_stock(product_id, quantity)
        if self._publisher and success:
            event = StockReleasedEvent(order_id=order_id, product_id=product_id, quantity=quantity)
            await self._publisher.publish("catalog.stock_released", event)
        return success

