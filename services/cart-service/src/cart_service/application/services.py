import uuid
from cart_service.application.dtos import AddToCartRequest
from cart_service.domain.entities import Cart, CartItem
from cart_service.domain.ports import CartRepositoryPort, CatalogClientPort
from nexus_core.domain.exceptions import BusinessRuleViolationException, ResourceNotFoundException


# Máximo de líneas distintas por carrito (evita carritos gigantes en Redis por usuario/invitado).
MAX_CART_LINES = 50


class CartService:
    def __init__(self, cart_repo: CartRepositoryPort, catalog_client: CatalogClientPort) -> None:
        self._repo = cart_repo
        self._catalog = catalog_client

    async def get_cart(self, user_id: str) -> Cart:
        return await self._repo.get_by_user_id(user_id)

    async def add_item(self, user_id: str, request: AddToCartRequest) -> Cart:
        product_data = await self._catalog.get_product_details(request.product_id)
        if not product_data:
            raise ResourceNotFoundException(f"Producto {request.product_id} no encontrado en el catálogo.")

        stock = int(product_data.get("stock", 0) or 0)
        cart = await self._repo.get_by_user_id(user_id)

        # Buscar si ya existe el ítem en el carrito; el stock se valida sobre la cantidad ACUMULADA.
        existing_item = next((item for item in cart.items if item.product_id == request.product_id), None)
        already = existing_item.quantity if existing_item else 0
        if stock < already + request.quantity:
            raise BusinessRuleViolationException("Stock insuficiente para añadir este producto.")
        if existing_item is None and len(cart.items) >= MAX_CART_LINES:
            raise BusinessRuleViolationException("El carrito alcanzó el máximo de productos distintos.")
        if existing_item:
            existing_item.quantity += request.quantity
        else:
            cart.items.append(
                CartItem(
                    product_id=request.product_id,
                    title=product_data["title"],
                    unit_price_clp=product_data["price_clp"],
                    quantity=request.quantity,
                    image_url=product_data.get("image_url"),
                )
            )

        return await self._repo.save(cart)

    async def update_item_quantity(self, user_id: str, product_id: uuid.UUID, quantity: int) -> Cart:
        cart = await self._repo.get_by_user_id(user_id)
        if quantity <= 0:
            cart.items = [item for item in cart.items if item.product_id != product_id]
        else:
            item = next((item for item in cart.items if item.product_id == product_id), None)
            if not item:
                raise ResourceNotFoundException("Ítem no encontrado en el carrito.")
            product_data = await self._catalog.get_product_details(product_id)
            if not product_data or int(product_data.get("stock", 0) or 0) < quantity:
                raise BusinessRuleViolationException("Stock insuficiente para esa cantidad.")
            item.quantity = quantity

        return await self._repo.save(cart)

    async def clear_cart(self, user_id: str) -> None:
        await self._repo.clear(user_id)

