import os

from ai_agent_service.config import Settings


def test_settings_use_inert_test_credentials_not_embedded_ones():
    """Con el entorno de tests, el validador no debe sustituir la clave de Groq embebida en el código."""
    s = Settings()
    assert s.GROQ_API_KEY == os.environ["GROQ_API_KEY"]
    assert s.SMTP_USER == os.environ["SMTP_USER"]
    assert s.SMTP_PASSWORD == os.environ["SMTP_PASSWORD"]
    assert s.SMTP_HOST == "127.0.0.1"
