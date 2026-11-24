"""Cadenas LCEL (LangChain Expression Language) para NexusBot.

El rol system es el prompt endurecido de security/prompt.py (sin datos externos). El catálogo, el historial y las
fuentes externas viajan en el mensaje humano como bloques <untrusted_data> (ver security.prompt.build_user_message).
"""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable

from ai_agent_service.security.prompt import SYSTEM_PROMPT

# Compatibilidad: otros módulos importaban este nombre.
NEXUSBOT_SYSTEM_PROMPT = SYSTEM_PROMPT


def _escape_braces(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


def build_nexusbot_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system", _escape_braces(SYSTEM_PROMPT)),
        MessagesPlaceholder(variable_name="messages", optional=True),
        ("human", "{query}"),
    ])


def build_lcel_generation_chain(llm) -> Runnable:
    """Construye la cadena composable LCEL: prompt | llm | StrOutputParser."""
    prompt = build_nexusbot_prompt()
    return prompt | llm | StrOutputParser()
