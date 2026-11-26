from dataclasses import dataclass, field
from typing import TypedDict
import uuid


@dataclass
class Genre:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""


@dataclass
class VideoGame:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = ""
    description: str = ""
    price_clp: int = 0
    stock: int = 0
    image_url: str | None = None
    genres: list[Genre] = field(default_factory=list)
    platform: str | None = None


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


class AssistantState(TypedDict, total=False):
    query: str
    tenant_id: str
    intent: str
    decision_metrics: dict
    chat_history: list[ChatMessage]
    retrieved_products: list[VideoGame]
    context: str
    external_context: str
    gaming_news: str
    price_comparison: str
    crew_analysis: str
    response: str
    # Identidad verificada del usuario final (security.context.UserContext); la usan los hooks de herramientas.
    user: object
