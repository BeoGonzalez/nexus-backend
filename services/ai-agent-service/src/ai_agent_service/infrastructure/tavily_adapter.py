"""Adaptador para búsqueda de noticias de videojuegos en tiempo real mediante la API de Tavily."""

import logging
import time
from typing import Any

import httpx

from ai_agent_service.domain.ports import GamingNewsPort
from ai_agent_service.config import get_settings
from ai_agent_service.infrastructure.llm_metrics import LLMMetrics, default_metrics

logger = logging.getLogger(__name__)


class TavilyNewsAdapter(GamingNewsPort):
    """Cliente asíncrono para la API de Tavily enfocado en noticias y novedades gamer."""

    def __init__(
        self,
        api_key: str | None = None,
        max_results: int | None = None,
        client: httpx.AsyncClient | None = None,
        metrics: LLMMetrics | None = None,
        timeout: float = 6.0,
    ) -> None:
        settings = get_settings()
        self._metrics = metrics
        # 6 s: una búsqueda nueva (sin caché de Tavily) tarda 3-4,5 s; con 4 s fallaba ~40 % de las veces.
        self._timeout = timeout
        self._api_key = api_key if api_key is not None else settings.TAVILY_API_KEY
        self._max_results = max_results or settings.TAVILY_MAX_RESULTS
        self._client = client
        self._endpoint = "https://api.tavily.com/search"

    async def _fetch_with_client(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> tuple[str, str]:
        response = await client.post(self._endpoint, json=payload)
        if response.status_code != 200:
            logger.warning("Tavily: la API respondió HTTP %d", response.status_code)
            return "Sin noticias recientes disponibles.", "error"

        data = response.json()
        results = data.get("results", [])
        direct_answer = data.get("answer", "")

        output_parts: list[str] = []
        if direct_answer:
            output_parts.append(f"Resumen de noticias: {direct_answer.strip()}")

        for i, r in enumerate(results[:self._max_results], 1):
            title = r.get("title", "").strip()
            content = r.get("content", "").strip()
            url = r.get("url", "").strip()
            if title:
                clean_content = content[:160] + "..." if len(content) > 160 else content
                output_parts.append(f"{i}. {title}: {clean_content} ({url})")

        if not output_parts:
            return "Sin novedades recientes sobre este título.", "empty"

        return "\n".join(output_parts), "ok"

    async def fetch_news(self, query: str) -> str:
        """Busca noticias recientes, parches y lanzamientos sobre el juego o tema."""
        if not self._api_key or not self._api_key.strip():
            logger.debug("Tavily API key no configurada; omitiendo búsqueda de noticias.")
            return "Sin noticias externas disponibles (API Key no configurada)."

        if not query or not query.strip():
            return "Sin noticias externas."

        search_query = f"{query.strip()} noticias videojuegos lanzamientos parches"

        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": search_query,
            "search_depth": "basic",
            "include_answer": True,
            "max_results": self._max_results,
            "topic": "news",
        }

        started = time.monotonic()
        text, outcome = "Sin noticias externas disponibles por el momento.", "error"
        try:
            if self._client:
                text, outcome = await self._fetch_with_client(self._client, payload)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    text, outcome = await self._fetch_with_client(client, payload)
        except httpx.TimeoutException:
            outcome = "timeout"
            logger.warning("Tavily: timeout tras %.1f s (límite %.0f s)", time.monotonic() - started, self._timeout)
        except Exception as exc:  # nunca la key ni la consulta en el log
            logger.warning("Tavily: fallo de la llamada (%s)", type(exc).__name__)
        (self._metrics or default_metrics()).external_call(
            source="tavily", outcome=outcome, seconds=time.monotonic() - started)
        return text

