from collections.abc import AsyncIterator

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from ai_agent_service.config import get_settings

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


class GroqLLMAdapter:
    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        temperature: float | None = None,
    ) -> None:
        settings = get_settings()
        self._temp = temperature if temperature is not None else settings.GROQ_TEMPERATURE
        # Sin key no hay fallback embebido: Groq rechazara la llamada y el error queda en los logs.
        key = (api_key or settings.GROQ_API_KEY or "").strip()

        raw_model = (model_name or settings.GROQ_MODEL_NAME or "").strip()
        if not raw_model or raw_model == "openai/gpt-oss-20b":
            model = DEFAULT_GROQ_MODEL
        else:
            model = raw_model

        self._llm = ChatGroq(
            api_key=key,
            model=model,
            temperature=self._temp,
            # LLM06: tope de tokens de salida, timeout y reintentos acotados por petición.
            max_tokens=settings.LLM_MAX_TOKENS,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
            streaming=True,
        )

    @property
    def llm(self) -> ChatGroq:
        return self._llm

    async def generate(self, system_prompt: str, user_message: str) -> str:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        response = await self._llm.ainvoke(messages)
        return str(response.content) if response and response.content else ""

    async def generate_stream(
        self, system_prompt: str, user_message: str,
    ) -> AsyncIterator[str]:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        async for chunk in self._llm.astream(messages):
            if chunk.content:
                yield str(chunk.content)
