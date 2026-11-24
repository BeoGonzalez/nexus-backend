"""SDD-Anchored End-to-End Purchase & Notification Flow Test.

Specification:
Criterio de Aceptación:
Cuando un comprador (iniciado sesión mediante AWS Cognito o mediante login local/normal)
completa una compra exitosa:
1. El pedido queda registrado con su identificador y su correo electrónico.
2. El pago es procesado y el pedido pasa a estado PAID.
3. Se emite el evento de dominio 'order.payment_succeeded' con el correo del comprador.
4. El microservicio de notificaciones despacha el correo de confirmación de compra
   directamente a la dirección de correo del comprador.
"""

import uuid
import pytest

from auth_service.application.dtos import LoginRequest, RegisterRequest
from auth_service.application.services import AuthService
from auth_service.infrastructure.cognito import CognitoAdapter
from cart_service.application.dtos import AddToCartRequest
from cart_service.application.services import CartService
from cart_service.domain.entities import Cart
from cart_service.domain.ports import CartRepositoryPort, CatalogClientPort
from catalog_service.application.dtos import CreateProductRequest
from catalog_service.application.services import CatalogService
from catalog_service.domain.entities import Product
from catalog_service.domain.ports import CatalogRepositoryPort
from nexus_security.dependencies import get_current_user
from nexus_testkit import sign_token
from notifications_service.application.handlers import NotificationEventHandler
from notifications_service.domain.ports import EmailSenderPort
from orders_service.domain.entities import Order, OrderItem, OrderStatus
from orders_service.domain.ports import OrderRepositoryPort


# ── Fakes & In-Memory Adapters para el flujo SDD ──

class InMemoryCatalogRepo(CatalogRepositoryPort):
    def __init__(self) -> None:
        self.products: dict[uuid.UUID, Product] = {}

    async def get_all(self, skip: int = 0, limit: int = 50) -> list[Product]:
        return list(self.products.values())

    async def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        return self.products.get(product_id)

    async def update_stock(self, product_id: uuid.UUID, delta: int) -> bool:
        p = self.products.get(product_id)
        if not p or (p.stock + delta) < 0:
            return False
        p.stock += delta
        return True

    async def create(self, product: Product) -> Product:
        self.products[product.id] = product
        return product


class InMemoryCartRepo(CartRepositoryPort):
    def __init__(self) -> None:
        self.carts: dict[str, Cart] = {}

    async def get_by_user_id(self, user_id: str) -> Cart:
        return self.carts.get(user_id, Cart(user_id=user_id))

    async def save(self, cart: Cart) -> Cart:
        self.carts[cart.user_id] = cart
        return cart

    async def clear(self, user_id: str) -> None:
        self.carts.pop(user_id, None)


class DirectCatalogClient(CatalogClientPort):
    def __init__(self, catalog_repo: CatalogRepositoryPort) -> None:
        self._repo = catalog_repo

    async def get_product_details(self, product_id: uuid.UUID) -> dict | None:
        p = await self._repo.get_by_id(product_id)
        if not p:
            return None
        return {"id": str(p.id), "title": p.title, "price_clp": p.price_clp, "stock": p.stock}


class InMemoryOrderRepo(OrderRepositoryPort):
    def __init__(self) -> None:
        self.orders: dict[uuid.UUID, Order] = {}
        self.outbox_events: list[dict] = []

    async def create(self, order: Order) -> Order:
        self.orders[order.id] = order
        return order

    async def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        return self.orders.get(order_id)

    async def get_by_user_id(self, user_id: str) -> list[Order]:
        return [o for o in self.orders.values() if o.user_id == user_id]

    async def update_status(self, order_id: uuid.UUID, status: OrderStatus) -> None:
        if order_id in self.orders:
            self.orders[order_id].status = status

    async def mark_paid_and_emit_event(self, order_id: uuid.UUID, payment_id: str) -> Order | None:
        order = self.orders.get(order_id)
        if not order:
            return None
        order.status = OrderStatus.PAID
        self.outbox_events.append({
            "event_type": "order.payment_succeeded",
            "order_id": str(order_id),
            "user_id": order.user_id,
            "user_email": order.user_email,
            "payment_id": payment_id,
            "amount_paid_clp": order.total_amount_clp,
        })
        return order


class SpyingEmailSender(EmailSenderPort):
    def __init__(self) -> None:
        self.inbox: list[dict] = []

    async def send_email(self, recipient: str, subject: str, html_content: str) -> bool:
        self.inbox.append({
            "to": recipient,
            "subject": subject,
            "html": html_content,
        })
        return True


# ── Tests SDD ──

@pytest.mark.asyncio
async def test_sdd_flow_successful_purchase_with_aws_cognito_buyer():
    """Escenario 1: Comprador autenticado vía AWS Cognito."""
    # 1. Autenticación con AWS Cognito (simulación de token verificado por Gateway)
    # La identidad sale SOLO de un JWT verificado (las cabeceras X-User-* ya no se aceptan: permitían suplantación).
    cognito_user = await get_current_user(
        authorization=f"Bearer {sign_token(sub='cognito-uuid-999', email='alex.gamer.cognito@gmail.com')}",
    )
    assert cognito_user.email == "alex.gamer.cognito@gmail.com"

    # 2. Catálogo: Crear producto
    catalog_repo = InMemoryCatalogRepo()
    catalog_service = CatalogService(catalog_repo)
    game = await catalog_service.create_product(
        CreateProductRequest(
            title="Black Myth: Wukong",
            description="Acción RPG",
            price_clp=39990,
            stock=10,
        )
    )

    # 3. Carrito: Agregar al carrito
    cart_repo = InMemoryCartRepo()
    cart_service = CartService(cart_repo, DirectCatalogClient(catalog_repo))
    cart = await cart_service.add_item(cognito_user.sub, AddToCartRequest(product_id=game.id, quantity=1))
    assert cart.total_amount_clp == 39990

    # 4. Órdenes: Crear la orden vinculada al comprador y su correo Cognito
    order_repo = InMemoryOrderRepo()
    order_id = uuid.uuid4()
    order = Order(
        id=order_id,
        user_id=cognito_user.sub,
        user_email=cognito_user.email,
        items=[
            OrderItem(
                product_id=game.id,
                product_title=game.title,
                quantity=1,
                unit_price_clp=game.price_clp,
            )
        ],
        status=OrderStatus.PENDING,
    )
    order.calculate_total()
    await order_repo.create(order)

    # 5. Pago exitoso: La orden se marca como PAID y se emite el evento de pago
    paid_order = await order_repo.mark_paid_and_emit_event(order_id, "transbank-auth-123456")
    assert paid_order.status == OrderStatus.PAID
    assert len(order_repo.outbox_events) == 1

    # 6. Notificaciones: El microservicio de notificaciones procesa el evento
    email_spy = SpyingEmailSender()
    notif_handler = NotificationEventHandler(email_spy)
    payment_event = order_repo.outbox_events[0]

    email_sent = await notif_handler.handle_payment_succeeded(payment_event)
    assert email_sent is True
    assert len(email_spy.inbox) == 1

    delivered_email = email_spy.inbox[0]
    assert delivered_email["to"] == "alex.gamer.cognito@gmail.com"
    assert "Boleta de Compra" in delivered_email["subject"]
    assert "transbank-auth-123456" in delivered_email["html"]
    assert str(order_id) in delivered_email["html"]


@pytest.mark.asyncio
async def test_sdd_flow_successful_purchase_with_local_credentials_buyer():
    """Escenario 2: Comprador autenticado vía Login Normal / Local."""
    # 1. Autenticación Local con adaptador
    auth_service = AuthService(CognitoAdapter())
    reg_user = await auth_service.register(
        RegisterRequest(name="Carlos Gomez", email="carlos.local@nexus.cl", password="Password123!")
    )
    assert reg_user.email == "carlos.local@nexus.cl"

    # 2. Catálogo & Órdenes
    order_repo = InMemoryOrderRepo()
    order_id = uuid.uuid4()
    order = Order(
        id=order_id,
        user_id=reg_user.id,
        user_email=reg_user.email,
        items=[
            OrderItem(
                product_id=uuid.uuid4(),
                product_title="Final Fantasy VII Rebirth",
                quantity=1,
                unit_price_clp=49990,
            )
        ],
        status=OrderStatus.PENDING,
    )
    order.calculate_total()
    await order_repo.create(order)

    # 3. Pago confirmado
    await order_repo.mark_paid_and_emit_event(order_id, "webpay-token-998877")

    # 4. Notificación
    email_spy = SpyingEmailSender()
    notif_handler = NotificationEventHandler(email_spy)
    payment_event = order_repo.outbox_events[0]

    await notif_handler.handle_payment_succeeded(payment_event)

    assert len(email_spy.inbox) == 1
    assert email_spy.inbox[0]["to"] == "carlos.local@nexus.cl"
    assert "Boleta de Compra" in email_spy.inbox[0]["subject"]

