"""Verificación de productos contra el catálogo en vivo (OWASP LLM07 Misinformation, LLM09 Vector store).

El vector store solo sirve para ENCONTRAR candidatos; el precio y el stock que ve el modelo salen del servicio
de catálogo (fuente de verdad). Productos retirados (404) no se recomiendan. Si el catálogo no responde, se
conservan los datos del índice y se registra la degradación (el asistente sigue funcionando).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from uuid import UUID

import httpx

from nexus_core.infrastructure.logging import log_security_event

from ai_agent_service.domain.entities import VideoGame

logger = logging.getLogger(__name__)


class CatalogVerifier:
    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def _fetch(self, client: httpx.AsyncClient, game: VideoGame) -> VideoGame | None | Exception:
        # El id viene de un registro validado como UUID: no puede inyectar rutas (SSRF/path traversal).
        product_id = UUID(str(game.id))
        try:
            r = await client.get(f"{self._base}/api/v1/catalog/products/{product_id}")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            data = r.json()
            if str(data.get("id")) != str(product_id):
                return game  # respuesta que no corresponde al producto pedido: se ignora
            return dataclasses.replace(game, price_clp=int(data["price_clp"]), stock=int(data["stock"]))
        except Exception as exc:  # catálogo caído o respuesta inválida
            return exc

    async def verify(self, games: list[VideoGame]) -> list[VideoGame]:
        if not games:
            return []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            results = await asyncio.gather(*(self._fetch(client, g) for g in games))
        verified: list[VideoGame] = []
        degraded = False
        for original, result in zip(games, results):
            if isinstance(result, Exception):
                degraded = True
                verified.append(original)
            elif result is not None:
                verified.append(result)
        if degraded:
            log_security_event("llm.degraded", level=logging.INFO, component="catalog_verification")
        return verified
