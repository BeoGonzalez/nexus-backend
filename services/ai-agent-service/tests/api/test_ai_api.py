import pytest

from nexus_testkit import auth_headers

BASE = "/api/v1/assistant"


async def test_app_imports_without_network():
    from ai_agent_service.main import app

    assert f"{BASE}/chat" in app.openapi()["paths"]


def test_default_wiring_never_builds_real_providers_in_tests():
    from ai_agent_service.presentation.router import _get_assistant_service

    with pytest.raises(AssertionError, match="proveedor real"):
        _get_assistant_service()


async def test_chat_streams_server_sent_events(client, sse):
    r = await client.post(f"{BASE}/chat", json={"query": "quiero un roguelike", "session_id": "s1"},
                          headers=auth_headers())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = sse(r.text)
    assert [e["type"] for e in events][0] == "products"
    assert events[-1] == {"type": "done"}


async def test_message_alias_is_accepted(client):
    r = await client.post(f"{BASE}/chat", json={"message": "hola"}, headers=auth_headers())
    assert r.status_code == 200


async def test_empty_query_is_422(client):
    assert (await client.post(f"{BASE}/chat", json={"query": "  "}, headers=auth_headers())).status_code == 422


async def test_reset_session_forgets_history(client, ports):
    await client.post(f"{BASE}/chat", json={"query": "me gustan los roguelikes", "session_id": "s9"}, headers=auth_headers())
    r = await client.delete(f"{BASE}/session/s9", headers=auth_headers())
    assert r.json() == {"status": "cleared", "session_id": "s9"}
    await client.post(f"{BASE}/chat", json={"query": "¿qué me recomiendas?", "session_id": "s9"}, headers=auth_headers())
    assert "roguelikes" not in ports["llm_port"].prompts[-1]


async def test_chat_requires_authentication(client):
    assert (await client.post(f"{BASE}/chat", json={"query": "hola"})).status_code == 401


async def test_history_does_not_leak_between_clients_without_session_id(client, ports):
    await client.post(f"{BASE}/chat", json={"query": "mi tarjeta termina en 4242"}, headers=auth_headers(sub="ana"))
    await client.post(f"{BASE}/chat", json={"query": "recomiéndame algo"}, headers=auth_headers(sub="mallory"))
    assert "4242" not in ports["llm_port"].prompts[-1]


async def test_health(client):
    assert (await client.get(f"{BASE}/health")).json()["status"] == "healthy"
