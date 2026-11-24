"""Una API key vacia significa "no configurada": nunca se reemplaza por una credencial embebida."""

from ai_agent_service.config import Settings


def test_empty_groq_key_is_not_replaced():
    assert Settings(GROQ_API_KEY="").GROQ_API_KEY == ""


def test_placeholder_groq_key_is_not_replaced_by_a_real_one():
    assert Settings(GROQ_API_KEY="your-groq-api-key").GROQ_API_KEY == "your-groq-api-key"


def test_secret_defaults_are_empty(monkeypatch):
    for var in ("GROQ_API_KEY", "PINECONE_API_KEY", "TAVILY_API_KEY", "SMTP_USER", "SMTP_PASSWORD",
                "GMAIL_USER", "GMAIL_APP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None)
    assert (s.GROQ_API_KEY, s.PINECONE_API_KEY, s.TAVILY_API_KEY) == ("", "", "")
    assert (s.SMTP_USER, s.SMTP_PASSWORD, s.GMAIL_USER, s.GMAIL_APP_PASSWORD) == ("", "", "", "")
