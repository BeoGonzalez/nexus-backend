"""LLM03 Excessive Agency (herramienta de correo) y LLM07 Misinformation (grounding de precios)."""

from ai_agent_service.security.context import UserContext
from ai_agent_service.security.grounding import extract_amounts, ungrounded_amounts
from ai_agent_service.security.tool_policy import EmailToolPolicy, render_email_body

ANA = UserContext(sub="ana", email="ana@nexus.cl", email_verified=True)


def test_email_goes_only_to_the_verified_user_address():
    decision = EmailToolPolicy(per_hour=3).authorize(ANA)
    assert decision.allowed and decision.recipient == "ana@nexus.cl"


def test_unverified_or_missing_email_is_denied():
    policy = EmailToolPolicy(per_hour=3)
    assert not policy.authorize(UserContext(sub="x", email="x@y.cl", email_verified=False)).allowed
    assert not policy.authorize(UserContext(sub="x", email=None, email_verified=True)).allowed


def test_email_rate_limit_per_user():
    policy = EmailToolPolicy(per_hour=2)
    assert [policy.authorize(ANA).allowed for _ in range(3)] == [True, True, False]


def test_policy_has_no_parameter_for_an_arbitrary_recipient():
    """Complete mediation: el destinatario NUNCA sale del texto que controla el modelo o el usuario."""
    import inspect

    assert "recipient" not in inspect.signature(EmailToolPolicy.authorize).parameters


def test_email_body_is_html_escaped():
    html = render_email_body('<script>alert(1)</script><a href="https://evil">clic</a>')
    assert "<script>" not in html and '<a href="https://evil">' not in html
    assert "&lt;script&gt;" in html


def test_extract_amounts_understands_clp_formats():
    assert extract_amounts("Hades II a $19.990 CLP, Celeste 9990 CLP y $4,990") == {19990, 9990, 4990}


def test_years_and_quantities_are_not_amounts():
    assert extract_amounts("Salió en 2025 y quedan 4 unidades") == set()


def test_ungrounded_amounts_detects_invented_prices():
    assert ungrounded_amounts("Te lo dejo en $1.990 CLP", allowed={19990}) == {1990}
    assert ungrounded_amounts("Cuesta $19.990 CLP", allowed={19990}) == set()
