import logging
import uuid
import httpx
from orders_service.application.dtos import CreateOrderRequest
from orders_service.config import get_settings
from orders_service.domain.entities import PAYABLE_STATUSES, Order, OrderItem, OrderStatus
from orders_service.domain.ports import OrderRepositoryPort
from nexus_core.domain.exceptions import BusinessRuleViolationException, ResourceNotFoundException

logger = logging.getLogger(__name__)


class OrderService:
    def __init__(self, order_repo: OrderRepositoryPort) -> None:
        self._order_repo = order_repo
        self._settings = get_settings()

    async def get_user_orders(self, user_id: str) -> list[Order]:
        return await self._order_repo.get_by_user_id(user_id)

    async def get_order_by_id(self, order_id: uuid.UUID) -> Order:
        order = await self._order_repo.get_by_id(order_id)
        if not order:
            raise ResourceNotFoundException(f"Orden {order_id} no encontrada.")
        return order

    async def create_order(
        self,
        user_id: str,
        request: CreateOrderRequest,
        user_email: str | None = None,
    ) -> Order:
        if not request.items:
            raise BusinessRuleViolationException("No se puede crear una orden vacía.")

        order_items: list[OrderItem] = []

        # Consultar precios y disponibilidad en Catalog Service vía HTTP Fast-Path
        async with httpx.AsyncClient(timeout=4.0) as client:
            for item_req in request.items:
                cat_url = f"{self._settings.CATALOG_SERVICE_URL}/api/v1/catalog/products/{item_req.product_id}"
                try:
                    resp = await client.get(cat_url)
                    if resp.status_code != 200:
                        raise ResourceNotFoundException(f"Producto {item_req.product_id} no disponible en catálogo.")
                    prod = resp.json()
                except httpx.RequestError as exc:
                    logger.error("Catalog service communication failed: %s", exc)
                    raise BusinessRuleViolationException("Servicio de catálogo no disponible temporalmente.")

                if prod.get("stock", 0) < item_req.quantity:
                    raise BusinessRuleViolationException(f"Stock insuficiente para '{prod.get('title')}'.")

                order_items.append(
                    OrderItem(
                        product_id=item_req.product_id,
                        product_title=prod.get("title"),
                        quantity=item_req.quantity,
                        unit_price_clp=prod.get("price_clp", 0),
                    )
                )

        order = Order(
            user_id=user_id,
            user_email=user_email,
            items=order_items,
            status=OrderStatus.PENDING,
            idempotency_key=request.idempotency_key,
        )
        order.calculate_total()

        return await self._order_repo.create(order)

    async def complete_payment(self, order_id: uuid.UUID, payment_id: str) -> Order:
        current = await self.get_order_by_id(order_id)
        if current.status not in PAYABLE_STATUSES:
            raise BusinessRuleViolationException("La orden ya fue pagada o no admite pago.")
        order = await self._order_repo.mark_paid_and_emit_event(order_id, payment_id)
        if not order:
            raise ResourceNotFoundException(f"Orden {order_id} no encontrada para procesar pago.")
        return order
