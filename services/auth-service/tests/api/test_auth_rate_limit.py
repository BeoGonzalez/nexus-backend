"""A07: fuerza bruta contra /auth/* y registro de logins fallidos."""

import json

import pytest

from nexus_core.domain.exceptions import UnauthorizedException
from nexus_testkit import policy_password


async def test_sixth_login_for_same_email_is_429_even_rotating_ips(client):
    codes = []
    for i in range(6):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "victim@nexus.cl", "password": "wrong-pass"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        )
        codes.append(r.status_code)
    assert codes[:5] == [200] * 5
    assert codes[5] == 429


@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/v1/auth/forgot-password", {"email": "victim@nexus.cl"}),
        ("/api/v1/auth/reset-password", {"email": "victim@nexus.cl", "confirmation_code": "123456", "new_password": policy_password()}),
        ("/api/v1/auth/confirm", {"email": "victim@nexus.cl", "confirmation_code": "123456"}),
        ("/api/v1/auth/register", {"name": "Ana", "email": "victim@nexus.cl", "password": policy_password()}),
    ],
)
async def test_other_credential_endpoints_are_rate_limited(client, path, body):
    codes = [(await client.post(path, json=body)).status_code for _ in range(6)]
    assert 429 in codes


async def test_failed_login_emits_masked_security_event(client, idp, capsys):
    from nexus_core.infrastructure.logging import setup_service_logging

    setup_service_logging("auth-test")
    idp.fail_with = UnauthorizedException("Correo electrónico o contraseña incorrectos.")
    r = await client.post("/api/v1/auth/login", json={"email": "ana.perez@nexus.cl", "password": "Sup3rS3cret!"})
    assert r.status_code == 401
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    failed = [e for e in events if e.get("security_event") == "auth.login_failed"]
    assert failed and failed[0]["email"] == "a***@nexus.cl"
    assert "Sup3rS3cret!" not in out and "ana.perez" not in out
