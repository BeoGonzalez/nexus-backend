from abc import ABC, abstractmethod
from notifications_service.domain.entities import NotificationMessage


class EmailSenderPort(ABC):
    @abstractmethod
    async def send_email(self, recipient: str, subject: str, html_content: str) -> bool:
        ...

