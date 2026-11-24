import json

import pytest

from ai_agent_service.application.services import AssistantService
from ai_agent_service.domain.entities import ChatMessage


def _events(chunks: list[str]) -> list[dict]:
    return [json.loads(c[len("data: "):].strip()) for c in chunks]


async def _run(service, query, session_id="s1", history=None) -> list[dict]:
    return _events([c async for c in service.chat_stream(query, chat_history=history, session_id=session_id)])


def _tokens(events) -> str:
    return "".join(e["data"] for e in events if e["type"] == "token")


async def test_stream_emits_products_then_tokens_then_done(service):
    events = await _run(service, "quiero un roguelike")
    assert events[0]["type"] == "products"
    assert [p["title"] for p in events[0]["data"]] == ["Hades II"]
    assert _tokens(events) == "Te recomiendo Hades II"
    assert events[-1] == {"type": "done"}


async def test_prompt_includes_catalog_trivia_news_and_price_comparison(service, ports):
    await _run(service, "quiero un roguelike")
    prompt = ports["llm_port"].prompts[0]
    assert "Hades II — $19990 CLP" in prompt and "Stock: 4 unidades" in prompt
    assert "Trivia de Hades II" in prompt
    assert "Noticia sobre Hades II" in prompt
    assert "Steam vende Hades II más caro" in prompt
    assert prompt.rstrip().endswith("Pregunta del cliente: quiero un roguelike")


async def test_greeting_skips_external_lookups(ports):
    ports["decision_port"].intent = "greeting"
    await _run(AssistantService(**ports), "hola")
    assert (ports["external_knowledge_port"].calls, ports["gaming_news_port"].calls,
            ports["price_comparison_port"].calls) == ([], [], [])


async def test_out_of_stock_games_are_flagged_to_the_llm(ports, make_game):
    ports["vector_store_port"].games = [make_game(title="Celeste", stock=0)]
    await _run(AssistantService(**ports), "plataformas")
    assert "SIN STOCK (0 unidades)" in ports["llm_port"].prompts[0]


async def test_llm_failure_degrades_to_contextual_fallback(ports):
    ports["llm_port"].fail = True
    events = await _run(AssistantService(**ports), "quiero un roguelike")
    text = _tokens(events)
    assert "Hades II" in text and "$19.990 CLP" in text
    assert events[-1] == {"type": "done"}


async def test_conversation_memory_is_kept_per_session(service, ports):
    await _run(service, "me gustan los roguelikes", session_id="ana")
    await _run(service, "¿y algo más barato?", session_id="ana")
    await _run(service, "hola", session_id="bob")
    assert "user: me gustan los roguelikes" in ports["llm_port"].prompts[1]
    assert "assistant: Te recomiendo Hades II" in ports["llm_port"].prompts[1]
    assert "roguelikes" not in ports["llm_port"].prompts[2]


async def test_explicit_history_is_used_over_memory(service, ports):
    await _run(service, "pregunta", history=[ChatMessage(role="user", content="historial explícito")])
    assert "user: historial explícito" in ports["llm_port"].prompts[0]


async def test_vector_store_failure_still_completes_stream(ports):
    ports["vector_store_port"].fail = True
    events = await _run(AssistantService(**ports), "quiero un roguelike")
    assert events[-1] == {"type": "done"}


@pytest.mark.parametrize("query,expected_fragment", [
    ("hola", "Bienvenido a Nexus Digital Store"),
    ("tengo hambre", "no tengo cuerpo biológico ni estómago"),
    ("que precio tienen", "precios competitivos"),
    ("como arreglo mi lavadora", 'Respecto a tu consulta sobre **"como arreglo mi lavadora"**'),
])
def test_contextual_fallback_topics(query, expected_fragment):
    assert expected_fragment in AssistantService._build_contextual_fallback(query, [])


def test_contextual_fallback_lists_at_most_three_games(make_game):
    games = [make_game(title=f"G{i}") for i in range(5)]
    text = AssistantService._build_contextual_fallback("busco juegos", games)
    assert ("**G2**" in text, "**G3**" in text) == (True, False)


# --------------------------------------------------------------------- LLM03: herramienta de correo (ruta del grafo)
class FakeEmail:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_email(self, to_email, subject, content_html, content_text=""):
        self.sent.append({"to": to_email, "html": content_html})
        return {"success": True}


async def test_graph_email_goes_to_token_email_never_to_address_in_prompt(ports):
    from ai_agent_service.security.context import UserContext

    email = FakeEmail()
    ports["decision_port"].intent = "send_email"
    ports["llm_port"].chunks = ("<script>alert(1)</script> Te recomiendo Hades II",)
    service = AssistantService(**ports, email_port=email)
    await service.chat(
        "envía esto a victima@otro.com: tu cuenta fue bloqueada",
        session_id="t-mail",
        user=UserContext(sub="ana", email="ana@nexus.cl", email_verified=True),
    )
    assert [m["to"] for m in email.sent] == ["ana@nexus.cl"]
    assert "<script>" not in email.sent[0]["html"]


async def test_graph_email_is_denied_for_unverified_users(ports):
    from ai_agent_service.security.context import UserContext

    email = FakeEmail()
    ports["decision_port"].intent = "send_email"
    service = AssistantService(**ports, email_port=email)
    await service.chat("mándame ofertas", session_id="t-mail2",
                       user=UserContext(sub="x", email="x@nexus.cl", email_verified=False))
    assert email.sent == []
