"""LLM06: el presupuesto de tokens se aplica ANTES de llamar al modelo y se carga con el uso REAL del proveedor."""

from ai_agent_service.presentation import router
from ai_agent_service.security.token_budget import MemoryCounterStore, TokenBudget
from nexus_testkit import auth_headers


def tight_budget(**overrides):
    limits = dict(user_tokens_per_day=10**9, global_tokens_per_day=10**9, global_tokens_per_minute=10**9,
                  global_requests_per_day=10**9)
    limits.update(overrides)
    return TokenBudget(MemoryCounterStore(), **limits)


async def test_user_without_token_budget_gets_429_and_the_model_is_not_called(client, ports, monkeypatch):
    b = tight_budget(user_tokens_per_day=100)
    monkeypatch.setattr(router, "TOKEN_BUDGET", b)
    await b.record("user-1", 100)
    r = await client.post("/api/v1/assistant/chat", json={"query": "hola"}, headers=auth_headers(sub="user-1"))
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert ports["llm_port"].prompts == []


async def test_site_wide_token_budget_exhausted_returns_503(client, ports, monkeypatch):
    b = tight_budget(global_tokens_per_day=100)
    monkeypatch.setattr(router, "TOKEN_BUDGET", b)
    await b.record("otro-usuario", 100)
    r = await client.post("/api/v1/assistant/chat", json={"query": "hola"}, headers=auth_headers(sub="user-2"))
    assert r.status_code == 503
    assert ports["llm_port"].prompts == []


async def test_real_provider_usage_is_charged_after_the_stream(client, ports, monkeypatch):
    b = tight_budget()
    monkeypatch.setattr(router, "TOKEN_BUDGET", b)
    ports["llm_port"].usage = {"input_tokens": 1500, "output_tokens": 234, "total_tokens": 1734}
    r = await client.post("/api/v1/assistant/chat", json={"query": "un juego de carreras"},
                          headers=auth_headers(sub="user-3"))
    assert r.status_code == 200
    assert (await b.usage("user-3"))["user_tokens_today"] == 1734


async def test_usage_is_estimated_when_the_provider_does_not_report_it(client, ports, monkeypatch):
    b = tight_budget()
    monkeypatch.setattr(router, "TOKEN_BUDGET", b)
    ports["llm_port"].usage = None
    r = await client.post("/api/v1/assistant/chat", json={"query": "un juego de carreras"},
                          headers=auth_headers(sub="user-4"))
    assert r.status_code == 200
    # System prompt + mensaje + respuesta: nunca se carga 0 (sería consumo gratis e ilimitado).
    assert (await b.usage("user-4"))["user_tokens_today"] > 500


def test_reasoning_model_runs_with_low_effort_to_save_output_tokens():
    from ai_agent_service.config import Settings
    from ai_agent_service.infrastructure.llm import chat_model_kwargs

    kwargs = chat_model_kwargs(Settings(_env_file=None))
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["max_tokens"] <= 1024
