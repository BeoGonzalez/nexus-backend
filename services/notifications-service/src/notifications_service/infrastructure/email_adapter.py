import logging
from email.message import EmailMessage
import aiosmtplib
from notifications_service.config import get_settings
from notifications_service.domain.ports import EmailSenderPort

logger = logging.getLogger("notifications.email")


class SmtpEmailAdapter(EmailSenderPort):
    def __init__(self) -> None:
        self._settings = get_settings()

    async def send_email(self, recipient: str, subject: str, html_content: str) -> bool:
        clean_user = (self._settings.SMTP_USER or "").strip()
        clean_password = (self._settings.SMTP_PASSWORD or "").strip()

        if not clean_user or not clean_password:
            logger.info("[Mock Email] To: %s | Subject: %s | Body: %s", recipient, subject, html_content[:80])
            return True

        message = EmailMessage()
        message["From"] = f"{self._settings.SMTP_FROM_NAME} <{clean_user}>"
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(html_content, subtype="html")

        try:
            await aiosmtplib.send(
                message,
                hostname=self._settings.SMTP_HOST,
                port=self._settings.SMTP_PORT,
                username=clean_user,
                password=clean_password,
                start_tls=True,
            )
            logger.info("Email sent successfully to %s", recipient)
            return True
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", recipient, exc)
            return False

