import os

from notifications_service.config import Settings


def test_settings_use_inert_test_credentials_not_embedded_ones():
    s = Settings()
    assert s.SMTP_USER == os.environ["SMTP_USER"] != ""
    assert s.SMTP_PASSWORD == os.environ["SMTP_PASSWORD"] != ""
    assert (s.SMTP_HOST, s.SMTP_PORT) == ("127.0.0.1", 1)
