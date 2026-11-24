import logging
import uuid
import httpx
from cart_service.config import get_settings
from cart_service.domain.ports import CatalogClientPort

logger = logging.getLogger(__name__)


class HttpCatalogClient(CatalogClientPort):
    def __init__(self) -> None:
        self._settings = get_settings()

    async def get_product_details(self, product_id: uuid.UUID) -> dict | None:
        url = f"{self._settings.CATALOG_SERVICE_URL}/api/v1/catalog/products/{product_id}"
        async with httpx.AsyncClient(timeout=3.0) as client:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.json()
                return None
            except Exception as exc:
                logger.error("Error communicating with catalog-service: %s", exc)
                return None

