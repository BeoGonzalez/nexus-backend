from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field


class UserRegisteredEvent(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str = "user.registered"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: str
    email: str
    full_name: str | None = None

