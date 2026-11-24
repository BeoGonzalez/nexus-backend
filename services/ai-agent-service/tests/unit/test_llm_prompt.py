"""LLM01 #1 / LLM08: system prompt declarativo, sin secretos, sin datos externos y con canario."""

import re

from ai_agent_service.application import chains
from ai_agent_service.security.prompt import CANARY, SYSTEM_PROMPT, build_user_message


def test_canary_is_random_and_embedded():
    assert re.fullmatch(r"NXC-[0-9a-f]{24}", CANARY)
    assert CANARY in SYSTEM_PROMPT


def test_system_prompt_has_no_placeholders_for_external_data():
    """El contenido externo nunca va en el rol system (heredaría autoridad de instrucción)."""
    assert "{context}" not in SYSTEM_PROMPT and "{external_context}" not in SYSTEM_PROMPT
    assert "{" not in SYSTEM_PROMPT.replace("{{", "")


def test_system_prompt_declares_data_boundary_and_denials():
    text = SYSTEM_PROMPT.lower()
    assert "untrusted_data" in text
    for rule in ("nunca reveles", "no sigas instrucciones", "no envíes", "no inventes precios"):
        assert rule in text


def test_system_prompt_contains_no_secrets():
    assert not re.search(r"gsk_|pcsk_|tvly-|AKIA|sk-|password|contraseña:", SYSTEM_PROMPT, re.IGNORECASE)


def test_user_message_wraps_every_external_source():
    msg = build_user_message(
        query="¿qué roguelike me recomiendas?",
        history=[{"role": "user", "content": "hola"}],
        catalog="1. Hades II — $19.990 CLP",
        sources={"wikipedia": "Trivia", "tavily": "Noticia", "cheapshark": "Steam más caro"},
        intent="recommendation",
    )
    for source in ("catalog", "history", "wikipedia", "tavily", "cheapshark"):
        assert f'<untrusted_data source="{source}">' in msg
    assert msg.rstrip().endswith("Pregunta del cliente: ¿qué roguelike me recomiendas?")


def test_user_message_skips_empty_sources():
    msg = build_user_message(query="hola", history=[], catalog="", sources={"tavily": ""}, intent="greeting")
    assert 'source="tavily"' not in msg


def test_lcel_chain_system_role_is_the_hardened_prompt():
    prompt = chains.build_nexusbot_prompt()
    system_template = prompt.messages[0].prompt.template
    assert system_template == SYSTEM_PROMPT.replace("{", "{{").replace("}", "}}") or CANARY in system_template
    assert "{context}" not in system_template
