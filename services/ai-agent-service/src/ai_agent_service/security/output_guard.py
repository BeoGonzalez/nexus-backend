"""Guardia de salida en streaming (hook agentResponse; LLM02, LLM08, LLM10, Agentic v2 §3.3.7).

Retiene una ventana de texto antes de emitirlo al cliente para poder:
- detectar la fuga del system prompt (canario o fragmentos literales) ANTES de que salga un solo carácter de ella,
- redactar secretos y tarjetas aunque lleguen partidos entre chunks,
- neutralizar marcado capaz de exfiltrar datos o ejecutar código (imágenes markdown, HTML, `javascript:`),
- eliminar caracteres de control/ANSI y acotar la longitud total (circuit breaker de salida).

Falla cerrado: ante una fuga detiene el stream y emite solo un mensaje fijo.
"""

from __future__ import annotations

import re
import unicodedata

from ai_agent_service.security.prompt import CANARY, PERSONA, SECURITY_RULES
from ai_agent_service.security.sanitize import mask_cards

REDACTED = "[REDACTADO]"
LEAK_REPLACEMENT = (
    "Lo siento, no puedo compartir mi configuración interna. "
    "¿Te ayudo a encontrar tu próximo videojuego? 🎮"
)
TRUNCATION_NOTICE = "\n\n[Respuesta recortada por longitud]"

_SECRET_RE = re.compile(
    r"gsk_[A-Za-z0-9]{16,}"  # Groq
    r"|pcsk_[A-Za-z0-9_]{12,}"  # Pinecone
    r"|tvly-[A-Za-z0-9-]{12,}"  # Tavily
    r"|lsv2_[A-Za-z0-9_]{12,}"  # LangSmith
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"  # AWS access key id
    r"|sk-[A-Za-z0-9_-]{20,}"  # OpenAI y similares
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"  # JWT
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{16,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
_MD_IMAGE_RE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(\s*(?:https?|javascript|data|vbscript|file):[^)\n]*\)", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>")
_DANGEROUS_SCHEME_RE = re.compile(r"\b(?:javascript|vbscript|data)\s*:", re.IGNORECASE)

_FRAGMENT_LEN = 40


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _prompt_fragments() -> tuple[str, ...]:
    """Inicio (40 caracteres normalizados) de cada línea larga del system prompt."""
    fragments = set()
    for line in (PERSONA + "\n" + SECURITY_RULES).splitlines():
        norm = _normalize(line.lstrip("-•0123456789. "))
        if len(norm) >= _FRAGMENT_LEN:
            fragments.add(norm[:_FRAGMENT_LEN])
    return tuple(fragments)


_PROMPT_FRAGMENTS = _prompt_fragments()


def redact_secrets(text: str) -> str:
    return mask_cards(_SECRET_RE.sub(REDACTED, text))


def _strip_controls(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)  # secuencias ANSI CSI
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf"))


def _neutralize_markup(text: str) -> str:
    text = _MD_IMAGE_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _HTML_TAG_RE.sub("", text)
    return _DANGEROUS_SCHEME_RE.sub("", text)


class StreamingOutputGuard:
    def __init__(self, *, window: int = 256, max_chars: int = 6000) -> None:
        self.window = window
        self.max_chars = max_chars
        self.leaked = False
        self.truncated = False
        self.leak_reason: str | None = None
        self._pending = ""
        self._emitted = 0
        self._stopped = False

    # ------------------------------------------------------------------ detección
    def _detect_leak(self, text: str) -> str | None:
        if CANARY in text or CANARY.lower() in text.lower():
            return "canary"
        norm = _normalize(text)
        if any(fragment in norm for fragment in _PROMPT_FRAGMENTS):
            return "system_prompt_fragment"
        return None

    def _safe_cut(self, text: str) -> int:
        """Punto de corte que no parte una palabra, una etiqueta ni un enlace todavía abiertos."""
        cut = len(text) - self.window
        if cut <= 0:
            return 0
        ws = max(text.rfind(" ", 0, cut), text.rfind("\n", 0, cut))
        if ws > 0:
            cut = ws + 1
        segment = text[:cut]
        for opener, closer in (("<", ">"), ("[", "]"), ("(", ")")):
            last_open = segment.rfind(opener)
            if last_open > segment.rfind(closer):
                cut = min(cut, last_open)
        if cut <= 0 and len(text) > self.window * 4:  # nada se resuelve: emite igualmente (ya transformado)
            cut = len(text) - self.window
        return max(cut, 0)

    def _emit(self, text: str) -> str:
        remaining = self.max_chars - self._emitted
        if len(text) > remaining:
            self.truncated = True
            self._stopped = True
            text = text[: max(remaining, 0)] + TRUNCATION_NOTICE
        self._emitted += len(text)
        return text

    def _transform(self, text: str) -> str:
        return _neutralize_markup(redact_secrets(text))

    # ------------------------------------------------------------------ API
    def feed(self, chunk: str) -> str:
        if self._stopped:
            return ""
        self._pending += _strip_controls(chunk)
        reason = self._detect_leak(self._pending)
        if reason:
            self.leaked, self.leak_reason, self._stopped = True, reason, True
            self._pending = ""
            return LEAK_REPLACEMENT
        self._pending = self._transform(self._pending)
        cut = self._safe_cut(self._pending)
        if cut == 0:
            return ""
        out, self._pending = self._pending[:cut], self._pending[cut:]
        return self._emit(out)

    def finish(self) -> str:
        if self._stopped:
            return ""
        self._stopped = True
        reason = self._detect_leak(self._pending)
        if reason:
            self.leaked, self.leak_reason = True, reason
            return LEAK_REPLACEMENT
        out = self._transform(self._pending)
        self._pending = ""
        return self._emit(out) if out else ""
