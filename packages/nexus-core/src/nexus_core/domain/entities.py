import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class BaseEntity:
    """Clase base de dominio para entidades con identidad y marcas temporales."""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

