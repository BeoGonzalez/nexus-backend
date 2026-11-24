"""Admisión de contexto (Agentic v2 §3.1.7): todo lo que entra al prompt pasa por aquí.

- LLM01 #5: elimina tag-block, variation selectors, zero-width, bidi y caracteres de control (contrabando invisible).
- LLM01 / LLM06 #10: neutraliza tokens especiales de plantillas de chat (no deben llegar como texto al modelo).
- LLM01 #6 / LLM05 #3 / LLM09: el contenido externo viaja en un canal etiquetado con su procedencia.
- LLM02 Tier 1 #2: minimiza PII antes de enviarla al proveedor del modelo o a la memoria.

Las heurísticas de inyección son SEÑALES para logging/alertas, nunca una sanitización (la guía lo exige así).
"""

from __future__ import annotations

import re
import unicodedata

# ----------------------------------------------------------------------------------------- caracteres invisibles
_INVISIBLE_RANGES = (
    (0xE0000, 0xE007F),  # tag block
    (0xFE00, 0xFE0F),  # variation selectors
    (0xE0100, 0xE01EF),  # variation selectors supplement
    (0x200B, 0x200F),  # zero-width + LRM/RLM
    (0x202A, 0x202E),  # bidi embeddings/overrides
    (0x2060, 0x2064),  # word joiner, invisible operators
    (0x2066, 0x2069),  # bidi isolates
    (0xFEFF, 0xFEFF),  # BOM / ZWNBSP
    (0x180E, 0x180E),  # mongolian vowel separator
    (0x00AD, 0x00AD),  # soft hyphen
)
_ALLOWED_CONTROLS = {"\n", "\t"}


def _is_invisible(ch: str) -> bool:
    cp = ord(ch)
    if any(lo <= cp <= hi for lo, hi in _INVISIBLE_RANGES):
        return True
    if ch in _ALLOWED_CONTROLS:
        return False
    return unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs")


# ----------------------------------------------------------------------------------------- tokens de plantilla
_SPECIAL_TOKEN_RE = re.compile(
    r"<\|[^|>\n]{1,40}\|>"  # <|im_start|>, <|eot_id|>, <|system|>, <|endoftext|> ...
    r"|\[/?INST\]"  # Llama 2
    r"|<</?SYS>>"  # Llama 2 system
    r"|</?s>"  # BOS/EOS literales
    r"|<start_of_turn>|<end_of_turn>",  # Gemma
    re.IGNORECASE,
)


def neutralize_special_tokens(text: str) -> str:
    return _SPECIAL_TOKEN_RE.sub("[token-bloqueado]", text)


def sanitize_text(text: str, max_len: int | None = None) -> str:
    """NFKC + sin invisibles/control + tokens de plantilla neutralizados + truncado."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(ch for ch in text if not _is_invisible(ch))
    text = neutralize_special_tokens(text)
    if max_len is not None and len(text) > max_len:
        text = text[:max_len]
    return text


# ----------------------------------------------------------------------------------------- contenido externo
_SOURCE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_DELIMITER_RE = re.compile(r"</?\s*untrusted_data[^>]*>", re.IGNORECASE)


def wrap_untrusted(source: str, text: str, max_len: int = 2000) -> str:
    """Envuelve contenido externo en un bloque etiquetado con su procedencia (dato, no instrucción)."""
    if not _SOURCE_RE.match(source):
        raise ValueError(f"Nombre de fuente inválido: {source!r}")
    body = _DELIMITER_RE.sub("[delimitador-eliminado]", sanitize_text(text, max_len=max_len))
    return f'<untrusted_data source="{source}">\n{body}\n</untrusted_data>'


# ----------------------------------------------------------------------------------------- señales de inyección
_INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|ignora|olvida|omite|descarta)\b.{0,40}\b(instructions?|instrucciones|reglas|rules|"
        r"previous|anterior(es)?|above|arriba|todo lo anterior)\b",
        re.IGNORECASE,
    ),
    "role_hijack": re.compile(
        r"\b(you are now|from now on you|ahora eres|a partir de ahora eres|act[uú]a como)\b|\bDAN\b|"
        r"\b(developer|dev|god|jailbreak)\s+mode\b|modo\s+(desarrollador|dios|sin restricciones)",
        re.IGNORECASE,
    ),
    "prompt_extraction": re.compile(
        r"\b(system\s*prompt|prompt\s+(de|del)\s+sistema|initial\s+instructions|instrucciones\s+(iniciales|ocultas|de sistema)|"
        r"tus\s+reglas|your\s+rules|hidden\s+(prompt|instructions))\b|"
        r"\b(repeat|repite|print|imprime)\b.{0,30}\b(above|arriba|verbatim|palabra por palabra|tal cual)\b",
        re.IGNORECASE,
    ),
    "exfiltration_markup": re.compile(r"!\[[^\]]*\]\(\s*https?://", re.IGNORECASE),
}


def detect_injection(text: str) -> list[str]:
    """Nombres de las heurísticas que coinciden (lista vacía = sin señales)."""
    normalized = sanitize_text(text)
    return [name for name, pattern in _INJECTION_PATTERNS.items() if pattern.search(normalized)]


# ----------------------------------------------------------------------------------------- PII
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_CARD_CANDIDATE_RE = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])")
_PHONE_RE = re.compile(r"(?<![\w$.])(?:\+\d{1,3}[ -]?)?(?:\(?\d{1,3}\)?[ -]?)?\d{4}[ -]?\d{4}(?![\w.])")


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _mask_card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return "[tarjeta]" if 13 <= len(digits) <= 19 and _luhn_ok(digits) else match.group(0)


def mask_cards(text: str) -> str:
    """Solo números de tarjeta válidos (Luhn)."""
    return _CARD_CANDIDATE_RE.sub(_mask_card, text)


def mask_pii(text: str) -> str:
    """Enmascara tarjetas (Luhn), emails y teléfonos; conserva precios ($19.990) y años."""
    text = mask_cards(text)
    text = _EMAIL_RE.sub("[email]", text)
    return _PHONE_RE.sub("[telefono]", text)
