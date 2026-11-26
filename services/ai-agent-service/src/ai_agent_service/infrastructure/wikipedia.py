import asyncio
import logging
import time

try:
    from langchain_community.utilities import WikipediaAPIWrapper
except ImportError:
    WikipediaAPIWrapper = None

try:
    import wikipedia
except ImportError:
    wikipedia = None

from ai_agent_service.domain.ports import ExternalKnowledgePort
from ai_agent_service.config import get_settings

logger = logging.getLogger(__name__)

# Mismo formato que el adaptador de CheapShark (política de User-Agent de Wikimedia).
WIKIMEDIA_USER_AGENT = "NexusDigitalStore/1.0 (comparador-gamer; soporte@nexusdigital.store) python-wikipedia"


class WikipediaAdapter(ExternalKnowledgePort):
    def __init__(
        self,
        lang: str | None = None,
        top_k_results: int | None = None,
        doc_content_chars_max: int | None = None,
        metrics=None,
    ) -> None:
        settings = get_settings()
        self._metrics = metrics
        # Wikimedia exige identificar al cliente: con el User-Agent genérico de la librería responde HTTP 429
        # desde la 3.ª consulta seguida. LangChain usa este mismo módulo, así que vale para ambos caminos.
        if wikipedia is not None and hasattr(wikipedia, "set_user_agent"):
            wikipedia.set_user_agent(WIKIMEDIA_USER_AGENT)
        self._lang = lang or settings.WIKIPEDIA_LANG
        self._top_k = top_k_results or settings.WIKIPEDIA_TOP_K
        self._chars_max = doc_content_chars_max or settings.WIKIPEDIA_MAX_CHARS
        self._wiki = None
        if WikipediaAPIWrapper:
            try:
                self._wiki = WikipediaAPIWrapper(
                    lang=self._lang,
                    top_k_results=self._top_k,
                    doc_content_chars_max=self._chars_max,
                )
            except Exception as e:
                logger.warning("Could not initialize WikipediaAPIWrapper: %s", e)
                self._wiki = None

    async def fetch_trivia(self, topic: str) -> str:
        if not topic:
            return "Sin datos externos."

        query = f"{topic} videojuego" if "videojuego" not in topic.lower() else topic

        failures: list[str] = []

        def _fetch() -> str:
            if self._wiki:
                try:
                    result = self._wiki.run(query)
                    return result.strip() if result else "Sin datos externos."
                except Exception as exc:
                    failures.append(type(exc).__name__)
            if wikipedia:
                try:
                    wikipedia.set_lang(self._lang)
                    search_results = wikipedia.search(query, results=self._top_k)
                    if search_results:
                        summary = wikipedia.summary(search_results[0], sentences=3)
                        return summary[:self._chars_max].strip() if summary else "Sin datos externos."
                except Exception as exc:
                    failures.append(type(exc).__name__)
            return "Sin datos externos."

        started = time.monotonic()
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _fetch)
        found = text != "Sin datos externos."
        outcome = "ok" if found else "error" if failures else "empty"
        if outcome == "error":
            logger.warning("Wikipedia: fallo de la consulta (%s)", ", ".join(failures))
        metrics = self._metrics
        if metrics is None:
            from ai_agent_service.infrastructure.llm_metrics import default_metrics

            metrics = default_metrics()
        metrics.external_call(source="wikipedia", outcome=outcome, seconds=time.monotonic() - started)
        return text

