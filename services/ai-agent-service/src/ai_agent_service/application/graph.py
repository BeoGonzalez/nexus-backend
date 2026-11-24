import logging
from langsmith import traceable
from langgraph.graph import StateGraph, END

from ai_agent_service.application.chains import build_lcel_generation_chain
from ai_agent_service.application.crew import run_nexus_crew
from ai_agent_service.domain.entities import AssistantState
from ai_agent_service.domain.ports import (
    DecisionEnginePort,
    EmailPort,
    EmbeddingPort,
    ExternalKnowledgePort,
    GamingNewsPort,
    LLMPort,
    PriceComparisonPort,
    VectorStorePort,
)
from ai_agent_service.config import get_settings
from ai_agent_service.security.context import UserContext
from ai_agent_service.security.memory import sanitize_history
from ai_agent_service.security.output_guard import StreamingOutputGuard
from ai_agent_service.security.prompt import SYSTEM_PROMPT, build_user_message
from ai_agent_service.security.sanitize import mask_pii, sanitize_text
from ai_agent_service.security.tool_policy import EmailToolPolicy, ToolDecision, render_email_body
from nexus_core.infrastructure.logging import log_security_event

logger = logging.getLogger(__name__)



def _real(text: str) -> str:
    """Descarta los textos de relleno ("Sin datos...", "Sin noticias...") para no enviarlos como fuente."""
    return "" if not text or text.startswith("Sin ") else text


def build_rag_graph(
    embedding_port: EmbeddingPort,
    llm_port: LLMPort,
    vector_store_port: VectorStorePort,
    external_knowledge_port: ExternalKnowledgePort | None = None,
    decision_port: DecisionEnginePort | None = None,
    gaming_news_port: GamingNewsPort | None = None,
    price_comparison_port: PriceComparisonPort | None = None,
    email_port: EmailPort | None = None,
    email_policy: EmailToolPolicy | None = None,
) -> StateGraph:
    settings = get_settings()
    email_policy = email_policy or EmailToolPolicy(per_hour=settings.ASSISTANT_EMAILS_PER_HOUR)

    @traceable(name="laya_decision")
    async def decide(state: AssistantState) -> dict:
        query = state.get("query", "")
        if decision_port:
            metrics = await decision_port.evaluate_decision(query)
            return {
                "intent": metrics.get("intent", "recommendation"),
                "decision_metrics": metrics,
            }
        return {"intent": "recommendation", "decision_metrics": {"engine": "default"}}

    @traceable(name="rag_retrieve")
    async def retrieve(state: AssistantState) -> dict:
        query = state["query"]
        intent = state.get("intent", "recommendation")
        decision_metrics = state.get("decision_metrics", {})

        embedding = await embedding_port.embed_text(query)
        video_games = await vector_store_port.similarity_search(
            embedding, top_k=settings.VECTOR_SEARCH_TOP_K,
        )

        context_parts = []
        for i, vg in enumerate(video_games, 1):
            genres = ", ".join(g.name for g in vg.genres) if vg.genres else "N/A"
            stock_info = f"Stock: {vg.stock} unidades" if vg.stock > 0 else "SIN STOCK (0 unidades)"
            context_parts.append(
                f"{i}. {vg.title} — ${vg.price_clp} CLP\n"
                f"   Géneros: {genres}\n"
                f"   {vg.description}\n"
                f"   {stock_info}"
            )

        context = "\n\n".join(context_parts) if context_parts else "No se encontraron videojuegos relevantes."

        # Ejecución en paralelo concurrente de Wikipedia, Tavily y CheapShark
        target_topic = video_games[0].title if video_games else query
        target_price = video_games[0].price_clp if video_games else 0
        should_fetch_trivia = decision_metrics.get("need_trivia", True) and (intent != "greeting")

        async def _fetch_wiki() -> str:
            if video_games and external_knowledge_port and should_fetch_trivia:
                try:
                    return await external_knowledge_port.fetch_trivia(video_games[0].title)
                except Exception as e:
                    logger.debug("External knowledge fetch error: %s", e)
            return "Sin datos externos."

        async def _fetch_news() -> str:
            if gaming_news_port and (intent != "greeting"):
                try:
                    return await gaming_news_port.fetch_news(target_topic)
                except Exception as e:
                    logger.debug("Gaming news fetch error (Tavily): %s", e)
            return "Sin noticias adicionales."

        async def _fetch_prices() -> str:
            if price_comparison_port and (intent != "greeting"):
                try:
                    comp_data = await price_comparison_port.compare_price(target_topic, target_price)
                    if comp_data.get("has_data"):
                        return comp_data.get("comparison_summary", "Sin datos comparativos de otras tiendas.")
                except Exception as e:
                    logger.debug("Price comparison error (CheapShark): %s", e)
            return "Sin datos comparativos de otras tiendas."

        import asyncio
        external_context, gaming_news, price_comparison = await asyncio.gather(
            _fetch_wiki(),
            _fetch_news(),
            _fetch_prices(),
        )

        logger.info("Retrieved %d games for query: %s (intent=%s)", len(video_games), query[:80], intent)
        return {
            "retrieved_products": video_games,
            "context": context,
            "external_context": external_context,
            "gaming_news": gaming_news,
            "price_comparison": price_comparison,
        }

    @traceable(name="crew_orchestrate")
    async def orchestrate(state: AssistantState) -> dict:
        query = state.get("query", "")
        catalog_context = state.get("context", "")
        external_context = state.get("external_context", "")
        intent = state.get("intent", "recommendation")

        if not settings.ENABLE_CREWAI_ORCHESTRATION:
            return {"crew_analysis": ""}

        if intent in ("greeting", "support", "stock_price", "send_email") or "No se encontraron" in catalog_context:
            return {"crew_analysis": ""}

        underlying_llm = getattr(llm_port, "llm", None)
        crew_analysis = await run_nexus_crew(
            query=query,
            catalog_context=catalog_context,
            external_context=external_context,
            llm=underlying_llm,
        )
        return {"crew_analysis": crew_analysis}

    @traceable(name="rag_generate")
    async def generate(state: AssistantState) -> dict:
        context = state.get("context", "")
        query = state["query"]
        intent = str(state.get("intent", "recommendation"))
        try:
            history = sanitize_history(state.get("chat_history") or [])
        except ValueError:
            history = []

        # Contexto externo como dato etiquetado (LLM01 #6): nunca dentro del rol system.
        user_message = build_user_message(
            query=mask_pii(sanitize_text(query)),
            history=history,
            catalog=context,
            sources={
                "wikipedia": _real(state.get("external_context", "")),
                "tavily": _real(state.get("gaming_news", "")),
                "cheapshark": _real(state.get("price_comparison", "")),
                "crew": state.get("crew_analysis", ""),
            },
            intent=intent,
        )

        underlying_llm = getattr(llm_port, "llm", None)
        raw_response = ""
        if underlying_llm:
            try:
                chain = build_lcel_generation_chain(underlying_llm)
                raw_response = await chain.ainvoke({"messages": [], "query": user_message})
            except Exception as exc:
                logger.debug("LCEL chain execution fallback to llm_port: %s", type(exc).__name__)
        if not raw_response:
            chunks: list[str] = []
            async for chunk in llm_port.generate_stream(SYSTEM_PROMPT, user_message):
                chunks.append(chunk)
            raw_response = "".join(chunks)

        # Hook agentResponse: misma guardia de salida que el stream.
        guard = StreamingOutputGuard(max_chars=settings.LLM_MAX_OUTPUT_CHARS)
        full_response = guard.feed(raw_response) + guard.finish()

        # Hook toolCallRequest (LLM03): el correo solo sale hacia el email VERIFICADO del token, nunca hacia una
        # dirección escrita en el mensaje (eso convertiría al agente en un relay de phishing vía prompt injection).
        user: UserContext | None = state.get("user")
        if email_port and intent == "send_email" and not guard.leaked:
            decision = (
                email_policy.authorize(user) if user else ToolDecision(False, "anonymous")
            )
            log_security_event(
                "llm.tool_call",
                level=logging.INFO if decision.allowed else logging.WARNING,
                tool="send_email",
                disposition="allow" if decision.allowed else "deny",
                reason=decision.reason,
                user_sub=user.sub if user else "anonymous",
            )
            if decision.allowed:
                try:
                    top_game = (state.get("retrieved_products") or [None])[0]
                    game_subject = f": {top_game.title[:80]}" if top_game else ""
                    mail_res = await email_port.send_email(
                        to_email=decision.recipient,
                        subject=f"🎮 Nexus Digital Store — Recomendación & Ofertas{game_subject}",
                        content_html=render_email_body(full_response),
                        content_text=full_response,
                    )
                    if mail_res.get("success"):
                        full_response += "\n\n✉️ *¡Listo! Te envié esta recomendación al correo de tu cuenta.*"
                except Exception as mail_exc:
                    logger.debug("Error enviando correo desde LangGraph: %s", type(mail_exc).__name__)

        updated_history = sanitize_history(
            history + [{"role": "user", "content": query}, {"role": "assistant", "content": full_response}]
        )
        return {
            "response": full_response,
            "chat_history": updated_history,
        }

    graph = StateGraph(AssistantState)
    graph.add_node("decide", decide)
    graph.add_node("retrieve", retrieve)
    graph.add_node("orchestrate", orchestrate)
    graph.add_node("generate", generate)

    graph.set_entry_point("decide")
    graph.add_edge("decide", "retrieve")
    graph.add_edge("retrieve", "orchestrate")
    graph.add_edge("orchestrate", "generate")
    graph.add_edge("generate", END)

    return graph
