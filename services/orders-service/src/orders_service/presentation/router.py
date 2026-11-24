from collections.abc import AsyncGenerator
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexus_core.infrastructure.database import (
    DatabaseConnectionConfig,
    create_db_engine,
    create_session_factory,
)
from nexus_core.domain.exceptions import ResourceNotFoundException
from nexus_security.dependencies import get_current_user
from nexus_security.jwt import TokenPayload
from orders_service.application.dtos import (
    CreateOrderRequest,
    OrderItemResponse,
    OrderResponse,
    ProcessPaymentRequest,
)
from orders_service.application.services import OrderService
from orders_service.config import get_settings
from orders_service.domain.entities import Order
from orders_service.infrastructure.repositories import PostgresOrderRepository

router = APIRouter(prefix="/api/v1/orders", tags=["Orders Service"])
settings = get_settings()

_engine = create_db_engine(DatabaseConnectionConfig(database_url=settings.DATABASE_URL))
_session_factory = create_session_factory(_engine)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with _session_factory() as session:
        yield session


def get_order_service(session: AsyncSession = Depends(get_db_session)) -> OrderService:
    repo = PostgresOrderRepository(session)
    return OrderService(repo)


def _to_response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        user_id=order.user_id,
        user_email=order.user_email,
        status=order.status,
        items=[
            OrderItemResponse(
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price_clp=item.unit_price_clp,
                subtotal_clp=item.subtotal_clp,
                product_title=item.product_title,
            )
            for item in order.items
        ],
        total_amount_clp=order.total_amount_clp,
        created_at=order.created_at,
    )


async def _get_owned_order(service: OrderService, order_id: uuid.UUID, user: TokenPayload) -> Order:
    """Devuelve la orden solo a su dueño (o a un admin). A los demas, 404: no revela si existe."""
    order = await service.get_order_by_id(order_id)
    if order.user_id != user.sub and user.role != "admin":
        raise ResourceNotFoundException(f"Orden {order_id} no encontrada.")
    return order


@router.get("/health")
async def health_check() -> dict:
    return {"status": "healthy", "service": "orders-service"}


@router.get("", response_model=list[OrderResponse])
async def get_my_orders(
    current_user: TokenPayload = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> list[OrderResponse]:
    orders = await service.get_user_orders(current_user.sub)
    return [_to_response(o) for o in orders]


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order_by_id(
    order_id: uuid.UUID,
    current_user: TokenPayload = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    order = await _get_owned_order(service, order_id, current_user)
    return _to_response(order)


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    request: CreateOrderRequest,
    current_user: TokenPayload = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    # Vinculamos la orden al comprador autenticado (Cognito o Local) con su email
    order = await service.create_order(
        user_id=current_user.sub,
        request=request,
        user_email=current_user.email,
    )
    return _to_response(order)


@router.post("/{order_id}/pay", response_model=OrderResponse)
async def pay_order(
    order_id: uuid.UUID,
    payment_req: ProcessPaymentRequest | None = None,
    current_user: TokenPayload = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    await _get_owned_order(service, order_id, current_user)
    payment_id = payment_req.payment_id if payment_req else f"pay-{uuid.uuid4().hex[:12]}"
    order = await service.complete_payment(order_id, payment_id)
    return _to_response(order)

