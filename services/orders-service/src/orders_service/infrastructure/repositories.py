from nexus_core.domain.exceptions import BusinessRuleViolationException
import json
import uuid
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_events.outbox import OutboxEventModel
from orders_service.domain.entities import PAYABLE_STATUSES, Order, OrderItem, OrderStatus
from orders_service.domain.ports import OrderRepositoryPort
from orders_service.infrastructure.models import OrderItemModel, OrderModel


class PostgresOrderRepository(OrderRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(model: OrderModel) -> Order:
        items = [
            OrderItem(
                id=item.id,
                product_id=item.product_id,
                product_title=item.product_title,
                quantity=item.quantity,
                unit_price_clp=item.unit_price_clp,
            )
            for item in model.items
        ]
        return Order(
            id=model.id,
            user_id=model.user_id,
            user_email=model.user_email,
            status=model.status,
            items=items,
            total_amount_clp=model.total_amount_clp,
            idempotency_key=model.idempotency_key,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def create(self, order: Order) -> Order:
        order_model = OrderModel(
            id=order.id,
            user_id=order.user_id,
            user_email=order.user_email,
            total_amount_clp=order.total_amount_clp,
            status=order.status,
            idempotency_key=order.idempotency_key,
            items=[
                OrderItemModel(
                    id=item.id,
                    product_id=item.product_id,
                    product_title=item.product_title,
                    quantity=item.quantity,
                    unit_price_clp=item.unit_price_clp,
                )
                for item in order.items
            ],
        )
        self._session.add(order_model)

        # Transactional Outbox Pattern: Insertar evento atómicamente en la misma transacción
        outbox_entry = OutboxEventModel(
            aggregate_type="Order",
            aggregate_id=str(order.id),
            event_type="order.created",
            payload_json=json.dumps({
                "order_id": str(order.id),
                "user_id": order.user_id,
                "user_email": order.user_email,
                "total_amount_clp": order.total_amount_clp,
                "items": [
                    {
                        "product_id": str(item.product_id),
                        "product_title": item.product_title,
                        "quantity": item.quantity,
                        "unit_price_clp": item.unit_price_clp,
                    }
                    for item in order.items
                ],
            }),
        )
        self._session.add(outbox_entry)

        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            if not order.idempotency_key:
                raise
            # Idempotencia segura: el MISMO comprador recupera su orden; otro usuario con la misma clave recibe 409
            # sin ver datos ajenos (la clave es global en la tabla, no debe servir para leer órdenes de terceros).
            existing = (
                await self._session.execute(select(OrderModel).where(OrderModel.idempotency_key == order.idempotency_key))
            ).scalar_one_or_none()
            if existing is not None and existing.user_id == order.user_id:
                return self._to_domain(existing)
            raise BusinessRuleViolationException("La clave de idempotencia ya fue utilizada.") from None
        await self._session.refresh(order_model)
        return self._to_domain(order_model)

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        stmt = select(OrderModel).where(OrderModel.id == order_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def get_by_user_id(self, user_id: str) -> list[Order]:
        stmt = select(OrderModel).where(OrderModel.user_id == user_id).order_by(OrderModel.created_at.desc())
        result = await self._session.execute(stmt)
        return [self._to_domain(m) for m in result.scalars().all()]

    async def update_status(self, order_id: uuid.UUID, status: OrderStatus) -> None:
        stmt = update(OrderModel).where(OrderModel.id == order_id).values(status=status)
        await self._session.execute(stmt)
        await self._session.commit()

    async def mark_paid_and_emit_event(self, order_id: uuid.UUID, payment_id: str) -> Order | None:
        order = await self.get_by_id(order_id)
        if not order:
            return None

        # 1. Actualizar estado a PAID de forma ATÓMICA y solo desde un estado pagable: dos pagos concurrentes de la
        #    misma orden no pueden emitir dos eventos order.payment_succeeded (doble entrega / doble correo).
        stmt = (
            update(OrderModel)
            .where(OrderModel.id == order_id, OrderModel.status.in_(PAYABLE_STATUSES))
            .values(status=OrderStatus.PAID)
        )
        result = await self._session.execute(stmt)
        if result.rowcount != 1:
            await self._session.rollback()
            raise BusinessRuleViolationException("La orden ya fue pagada o no admite pago.")

        # 2. Agregar evento de pago exitoso a la tabla Outbox
        outbox_entry = OutboxEventModel(
            aggregate_type="Order",
            aggregate_id=str(order_id),
            event_type="order.payment_succeeded",
            payload_json=json.dumps({
                "order_id": str(order_id),
                "user_id": order.user_id,
                "user_email": order.user_email,
                "payment_id": payment_id,
                "amount_paid_clp": order.total_amount_clp,
                "items": [
                    {
                        "product_id": str(item.product_id),
                        "product_title": item.product_title,
                        "quantity": item.quantity,
                        "unit_price_clp": item.unit_price_clp,
                    }
                    for item in order.items
                ],
            }),
        )
        self._session.add(outbox_entry)
        await self._session.commit()

        order.status = OrderStatus.PAID
        return order
