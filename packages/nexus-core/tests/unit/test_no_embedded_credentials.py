"""Ninguna credencial real puede vivir en el codigo ni en compose.yml: terminaria en git y en las
imagenes de ECR. En AWS vienen de Secrets Manager; en local, de .env (ignorado por git)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]

PATTERNS = {
    "Groq API key": re.compile(r"gsk_[A-Za-z0-9]{40,}"),
    "Pinecone API key": re.compile(r"pcsk_[A-Za-z0-9_]{40,}"),
    "Tavily API key": re.compile(r"tvly-(dev|prod)-[A-Za-z0-9-]{20,}"),
    "Gmail app password": re.compile(r"[\"'=:-]\s*[a-z]{4} [a-z]{4} [a-z]{4} [a-z]{4}\b"),
}


def _source_files():
    for base in ("services", "packages", "src"):
        for path in (ROOT / base).rglob("*"):
            if path.suffix in {".py", ".toml", ".yml", ".yaml", ".json", ".sh"} and not any(
                part in {".venv", "__pycache__", "tests"} for part in path.parts
            ):
                yield path
    yield ROOT / "compose.yml"


@pytest.mark.parametrize("name", sorted(PATTERNS))
def test_no_embedded_credentials(name):
    hits = [
        f"{p.relative_to(ROOT)}:{n}"
        for p in _source_files()
        if p.exists()
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
        if PATTERNS[name].search(line)
    ]
    assert hits == [], f"{name} embebida en: {hits}"
