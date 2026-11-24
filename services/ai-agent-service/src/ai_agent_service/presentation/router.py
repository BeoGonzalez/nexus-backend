from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import MemorySaver

from ai_agent_service.config import get_settings
from nexus_security.dependencies import get_current_user
from nexus_security.jwt import TokenPayload
from nexus_core.infrastructure.logging import log_security_event
from ai_agent_service.security.context import UserContext
from ai_agent_service.security.governor import QuotaExceeded, UsageGovernor
from ai_agent_service.security.memory import ThreadRegistry, thread_id_for
from ai_agent_service.application.dtos import ChatRequest
from ai_agent_service.application.services import AssistantService
from ai_agent_service.infrastructure.cheapshark_adapter import CheapSharkPriceAdapter
from ai_agent_service.infrastructure.embeddings import HuggingFaceEmbeddingAdapter
from ai_agent_service.infrastructure.laya_adapter import LayaDecisionAdapter
from ai_agent_service.infrastructure.llm import GroqLLMAdapter
from ai_agent_service.infrastructure.pinecone_store import PineconeVectorStoreAdapter
from ai_agent_service.infrastructure.tavily_adapter import TavilyNewsAdapter
from ai_agent_service.infrastructure.wikipedia import WikipediaAdapter

router = APIRouter(prefix="/assistant", tags=["AI Shopping Assistant"])

# Checkpointer en memoria compartido para persistencia multi-turno por session_id (thread_id)
_shared_checkpointer = MemorySaver()


def _get_assistant_service() -> AssistantService:
    settings = get_settings()
    vector_store = PineconeVectorStoreAdapter(
        api_key=settings.PINECONE_API_KEY,
        index_name=settings.PINECONE_INDEX_NAME,
        namespace=settings.PINECONE_NAMESPACE,
    )
    gaming_news_adapter = (
        TavilyNewsAdapter(
            api_key=settings.TAVILY_API_KEY,
            max_results=settings.TAVILY_MAX_RESULTS,
        )
        if settings.TAVILY_API_KEY
        else None
    )
    price_comparison_adapter = (
        CheapSharkPriceAdapter(
            usd_clp_rate=settings.CHEAPSHARK_USD_CLP_RATE,
        )
        if settings.CHEAPSHARK_ENABLED
        else None
    )
    from ai_agent_service.infrastructure.email_adapter import GmailEmailAdapter
    email_adapter = (
        GmailEmailAdapter()
        if (bool(getattr(settings, "SMTP_USER", None)) or bool(getattr(settings, "GMAIL_USER", None)))
        else None
    )

    return AssistantService(
        embedding_port=HuggingFaceEmbeddingAdapter(model_name=settings.EMBEDDING_MODEL_NAME),
        llm_port=GroqLLMAdapter(
            api_key=settings.GROQ_API_KEY,
            model_name=settings.GROQ_MODEL_NAME,
            temperature=settings.GROQ_TEMPERATURE,
        ),
        vector_store_port=vector_store,
        external_knowledge_port=WikipediaAdapter(
            lang=settings.WIKIPEDIA_LANG,
            top_k_results=settings.WIKIPEDIA_TOP_K,
            doc_content_chars_max=settings.WIKIPEDIA_MAX_CHARS,
        ),
        decision_port=LayaDecisionAdapter(
            model_name=settings.LAYA_MODEL_NAME,
        ),
        checkpointer=_shared_checkpointer,
        gaming_news_port=gaming_news_adapter,
        price_comparison_port=price_comparison_adapter,
        email_port=email_adapter,
    )


def _governor() -> UsageGovernor:
    """Gobernador de consumo del proceso (LLM06), creado perezosamente con la configuración vigente."""
    global GOVERNOR
    if GOVERNOR is None:
        settings = get_settings()
        GOVERNOR = UsageGovernor(
            per_minute=settings.LLM_REQUESTS_PER_MINUTE,
            per_day=settings.LLM_REQUESTS_PER_DAY,
            max_concurrent=settings.LLM_MAX_CONCURRENT_STREAMS,
            global_per_day=settings.LLM_GLOBAL_REQUESTS_PER_DAY,
            enabled=settings.ASSISTANT_ENABLED,
        )
    return GOVERNOR


def _registry() -> ThreadRegistry:
    """Registro LRU de hilos sobre el checkpointer compartido (se recrea si el checkpointer cambia)."""
    global _REGISTRY
    if _REGISTRY is None or _REGISTRY[0] is not _shared_checkpointer:
        _REGISTRY = (_shared_checkpointer, ThreadRegistry(_shared_checkpointer, get_settings().ASSISTANT_MAX_THREADS))
    return _REGISTRY[1]


GOVERNOR: UsageGovernor | None = None
_REGISTRY: tuple[MemorySaver, ThreadRegistry] | None = None


def _user_context(token: TokenPayload) -> UserContext:
    return UserContext(sub=token.sub, email=token.email, email_verified=token.email_verified)


@router.post("/chat")
async def chat_stream(
    body: ChatRequest,
    user: TokenPayload = Depends(get_current_user),
    service: AssistantService = Depends(_get_assistant_service),
) -> StreamingResponse:
    # Hook sessionStart: kill switch y cuotas ANTES de tocar el modelo (LLM06, Agentic v2 §3.3.8).
    try:
        lease = _governor().acquire(user.sub)
    except QuotaExceeded as exc:
        log_security_event("llm.quota_exceeded", user_sub=user.sub, reason=exc.reason)
        if exc.reason in ("disabled", "global_budget"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="El asistente no está disponible en este momento.",
                headers={"Retry-After": str(exc.retry_after)},
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Has alcanzado el límite de mensajes del asistente. Inténtalo más tarde.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    # Memoria ligada al usuario autenticado: un session_id ajeno no abre la conversación de otro (A01/LLM02).
    thread_id = thread_id_for(user.sub, body.session_id)
    _registry().touch(thread_id)

    async def guarded_stream():
        try:
            async for event in service.chat_stream(
                query=body.query,
                chat_history=body.to_chat_messages(),
                session_id=thread_id,
                user=_user_context(user),
            ):
                yield event
        finally:
            lease.release()

    return StreamingResponse(
        guarded_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/session/{session_id}")
async def reset_session(
    session_id: str = Path(..., pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Restablece la memoria de la sesión del PROPIO usuario (nunca la de otro)."""
    _registry().forget(thread_id_for(user.sub, session_id))
    return {"status": "cleared", "session_id": session_id}


@router.get("/health")
async def health_check() -> dict:
    return {"status": "healthy", "service": "ai-agent-service"}
