"""Memoria conversacional segura (Agentic v2 §3.1.6 Memory Security; LLM02; LLM06).

- Aislamiento: el hilo de LangGraph se deriva del `sub` del JWT + `session_id`; un `session_id` ajeno no da acceso
  a la memoria de otro usuario (antes: cualquiera que adivinara el id leía la conversación).
- Escrituras saneadas: solo roles user/assistant, contenido normalizado, PII enmascarada y tamaño acotado; la memoria
  recuperada se trata igualmente como dato no confiable (vuelve a pasar por wrap_untrusted al construir el prompt).
- Capacidad: número máximo de hilos por proceso con expulsión del menos reciente (sin crecimiento ilimitado).
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping

from ai_agent_service.security.sanitize import mask_pii, sanitize_text

ALLOWED_ROLES = frozenset({"user", "assistant"})
MAX_HISTORY_MESSAGES = 20
MAX_MESSAGE_CHARS = 4000


def thread_id_for(user_sub: str, session_id: str | None) -> str:
    digest = hashlib.sha256(user_sub.encode("utf-8")).hexdigest()[:24]
    return f"u{digest}:{session_id or 'default'}"


def sanitize_history(
    history: Iterable[Mapping[str, object] | object],
    *,
    max_messages: int = MAX_HISTORY_MESSAGES,
    max_chars: int = MAX_MESSAGE_CHARS,
) -> list[dict[str, str]]:
    """Valida roles (ValueError si alguno no es user/assistant), sanea, enmascara PII y recorta."""
    clean: list[dict[str, str]] = []
    for item in history:
        role = item.get("role") if isinstance(item, Mapping) else getattr(item, "role", None)
        content = item.get("content") if isinstance(item, Mapping) else getattr(item, "content", "")
        if role not in ALLOWED_ROLES:
            raise ValueError(f"Rol no permitido en el historial: {role!r}")
        clean.append({"role": str(role), "content": mask_pii(sanitize_text(str(content or ""), max_len=max_chars))})
    return clean[-max_messages:]


class ThreadRegistry:
    """Registro LRU de hilos vivos sobre un checkpointer de LangGraph."""

    def __init__(self, checkpointer, max_threads: int = 5000) -> None:
        self._checkpointer = checkpointer
        self._max = max_threads
        self._threads: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def touch(self, thread_id: str) -> None:
        evicted: list[str] = []
        with self._lock:
            self._threads[thread_id] = None
            self._threads.move_to_end(thread_id)
            while len(self._threads) > self._max:
                old, _ = self._threads.popitem(last=False)
                evicted.append(old)
        for old in evicted:
            self._checkpointer.delete_thread(old)

    def owns(self, thread_id: str) -> bool:
        with self._lock:
            return thread_id in self._threads

    def forget(self, thread_id: str) -> None:
        with self._lock:
            self._threads.pop(thread_id, None)
        self._checkpointer.delete_thread(thread_id)
