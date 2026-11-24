from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_agent_service.domain.entities import ChatMessage

# Hook userMessage / context admission (OWASP LLM01, LLM06): límites ANTES de gastar un solo token.
MAX_QUERY_CHARS = 2000
MAX_HISTORY_ITEMS = 50  # se aceptan para no romper clientes con chats largos; al modelo llegan solo los últimos 20
MAX_HISTORY_ITEM_CHARS = 8000


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Solo user/assistant: un rol "system" enviado por el cliente sería inyección de instrucciones privilegiadas.
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=MAX_HISTORY_ITEM_CHARS)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=MAX_QUERY_CHARS, description="Pregunta o consulta del usuario")
    message: str | None = Field(default=None, max_length=MAX_QUERY_CHARS, description="Alias opcional para query")
    chat_history: list[HistoryItem] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)
    session_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
        description="ID de sesión del cliente; el servidor lo liga al usuario autenticado",
    )

    @model_validator(mode="after")
    def validate_query(self) -> "ChatRequest":
        if not self.query and self.message:
            self.query = self.message
        if not self.query or not self.query.strip():
            raise ValueError("El campo 'query' o 'message' es requerido y no puede estar vacío.")
        return self

    def to_chat_messages(self) -> list[ChatMessage]:
        return [ChatMessage(role=item.role, content=item.content) for item in self.chat_history]
