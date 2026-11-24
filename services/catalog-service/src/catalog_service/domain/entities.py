import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from nexus_core.domain.entities import BaseEntity


@dataclass
class Genre(BaseEntity):
    name: str = ""


@dataclass
class Platform(BaseEntity):
    name: str = ""


@dataclass
class Product(BaseEntity):
    title: str = ""
    description: str = ""
    price_clp: int = 0
    stock: int = 0
    image_url: str | None = None
    platform: Platform | None = None
    genres: list[Genre] = field(default_factory=list)


# Alias de compatibilidad
VideoGame = Product

