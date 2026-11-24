from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class NotificationChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"


@dataclass
class NotificationMessage:
    recipient: str
    subject: str
    body_html: str
    channel: NotificationChannel = NotificationChannel.EMAIL
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

