from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


@dataclass
class User:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    email: str = ""
    role: str = "customer"
    banned: bool = False
    email_verified: bool = False
    image: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_admin(self) -> bool:
        return (self.role or "").strip().lower() == "admin"

    @property
    def is_active(self) -> bool:
        return not self.banned

