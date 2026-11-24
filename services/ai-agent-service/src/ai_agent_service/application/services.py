import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from langgraph.checkpoint.memory import MemorySaver
from langsmith import traceable

from ai_agent_service.application.crew import run_nexus_crew
from ai_agent_service.application.graph import build_rag_graph
from ai_agent_service.domain.entities import AssistantState, ChatMessage
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
from ai_agent_service.security.grounding import extract_amounts, ungrounded_amounts
from ai_agent_service.security.memory import sanitize_history
from ai_agent_service.security.output_guard import StreamingOutputGuard
from ai_agent_service.security.prompt import MAX_QUERY_CHARS, SYSTEM_PROMPT, build_user_message
from ai_agent_service.security.sanitize import detect_injection, mask_pii, sanitize_text
from nexus_core.infrastructure.logging import log_security_event

logger = logging.getLogger(__name__)


class AssistantService:
    def __init__(
        self,
        embedding_port: EmbeddingPort,
        llm_port: LLMPort,
        vector_store_port: VectorStorePort,
        external_knowledge_port: ExternalKnowledgePort | None = None,
        decision_port: DecisionEnginePort | None = None,
        checkpointer: MemorySaver | None = None,
        gaming_news_port: GamingNewsPort | None = None,
        price_comparison_port: PriceComparisonPort | None = None,
        email_port: EmailPort | None = None,
    ) -> None:
        self._embedding = embedding_port
        self._llm = llm_port
        self._vector_store = vector_store_port
        self._external_knowledge = external_knowledge_port
        self._decision = decision_port
        self._gaming_news = gaming_news_port
        self._price_comparison = price_comparison_port
        self._email = email_port
        self._checkpointer = checkpointer if checkpointer is not None else MemorySaver()
        self._graph = build_rag_graph(
            embedding_port,
            llm_port,
            vector_store_port,
            external_knowledge_port,
            decision_port,
            gaming_news_port,
            price_comparison_port,
            email_port,
        ).compile(checkpointer=self._checkpointer)

    @staticmethod
    def _build_contextual_fallback(query: str, video_games: list) -> str:
        q_lower = query.lower().strip()
        
        # 1. Saludos e introducciones
        greetings = ("hola", "buenas", "hey", "saludos", "que tal", "buenos dias", "buenas tardes", "buenas noches")
        if any(g in q_lower for g in greetings) and len(q_lower.split()) <= 4:
            return (
                "¡Hola! Bienvenido a Nexus Digital Store. 🎮\n\n"
                "Soy tu asesor gamer para encontrar videojuegos de PC. "
                "¿Qué tipo de experiencia buscas hoy? Cuéntame sobre tus géneros predilectos "
                "(RPG, Acción, Terror, Estrategia, Carreras) o si buscas algo para jugar en solitario o con amigos."
            )

        # 2. Sed y bebidas
        if any(w in q_lower for w in ("sed", "beber", "bebida", "agua", "tomar")):
            return (
                "¡Jaja! Como inteligencia artificial no tengo cuerpo biológico ni garganta, así que no tengo sed ni necesito beber líquidos. "
                "¡Mi única energía son los servidores y los buenos videojuegos! 🥤🎮\n\n"
                "Pero tú mantente hidratado para esas partidas largas. ¿Qué juego te gustaría jugar hoy?"
            )

        # 3. Hambre, comida y recetas
        if any(w in q_lower for w in ("hambre", "comes", "comida", "almuerzo", "cena", "desayuno", "comer", "cocina", "receta")):
            return (
                "¡Jaja! Como inteligencia artificial no tengo cuerpo biológico ni estómago, así que no estoy relacionado con el hambre ni necesito comida humana. "
                "¡Mi único combustible son los servidores, los gigabytes y los buenos videojuegos! 🍕🎮\n\n"
                "Eso sí, si a ti te apasiona la gastronomía o comida en el mundo gamer, hay simuladores culinarios increíbles como Overcooked o Chef RPG. "
                "Y para acompañar tu comida o snack, ¿qué tipo de juego te gustaría probar hoy?"
            )

        # 4. Clima y meteorología
        if any(w in q_lower for w in ("clima", "tiempo", "llov", "lluv", "temperatura", "frio", "calor", "soleado", "nublado", "pronostico", "meteorolog", "tormenta", "nieve")):
            return (
                "No puedo ver el clima exterior ni tengo sensores meteorológicos para saber si llueve, hace frío o hay sol en tu ciudad... ☀️🌧️\n\n"
                "Pero desde la terminal de Nexus te puedo asegurar que cualquier clima es perfecto para quedarse jugando con el PC bien ventilado. "
                "¿Buscas alguna recomendación de juego para pasar el día?"
            )

        # 4. Autos, mecánica y reparación
        if any(w in q_lower for w in ("auto", "coche", "carro", "mecanica", "motor", "rueda", "neumatico", "aceite", "reparar", "taller", "trafico")):
            return (
                "En cuanto a tu consulta sobre mecánica o vehículos del mundo real: como IA de Nexus no soy mecánico ni tengo un taller de reparación automotriz. "
                "¡Donde sí soy experto es en la velocidad y el asfalto virtual! 🏎️💨\n\n"
                "¿Te gustaría que busquemos algún simulador de carreras, rally o conducción para sentir la adrenalina de los motores en PC?"
            )

        # 5. Salud, medicina y síntomas
        if any(w in q_lower for w in ("salud", "medico", "medicina", "pastilla", "enfermo", "dolor", "sintoma", "remedio", "farmacia", "hospital")):
            return (
                "Respecto a tu consulta de salud: soy un asistente virtual de videojuegos y no poseo formación médica ni puedo recetar medicamentos (¡aquí solo manejamos botiquines y pociones de salud en pantalla!). 💊❤️\n\n"
                "Si no te sientes bien, por favor consulta a un profesional de la salud. Y para distraerte y descansar la mente, ¿hay algún juego relajante o aventura que te gustaría explorar?"
            )

        # 6. Tareas, matemáticas, física, colegio o universidad
        if any(w in q_lower for w in ("tarea", "matematica", "calculo", "colegio", "universidad", "profesor", "examen", "fisica", "quimica")):
            return (
                "Sobre tu consulta de estudio o tareas académicas: mi base de conocimiento en Nexus está 100% orientada al catálogo y la cultura gamer de PC, así que no resuelvo deberes escolares ni ecuaciones. 📚🎮\n\n"
                "¡Pero una vez que apruebes ese examen, aquí te espero para celebrarlo con una buena partida! ¿Qué juego tienes en la mira para jugar después?"
            )

        # 7. Política, elecciones y gobierno
        if any(w in q_lower for w in ("politica", "presidente", "eleccion", "gobierno", "ley", "voto", "partido")):
            return (
                "En cuanto a temas políticos o de gobierno: en Nexus nos enfocamos pura y exclusivamente en el entretenimiento y los videojuegos, por lo que no tomo posturas ni analizo política del mundo real. 🏛️🎮\n\n"
                "¡Las únicas batallas y estrategias que seguimos son dentro de los servidores de juego! ¿Te interesa algún juego de estrategia o táctica en el catálogo?"
            )

        # 8. Relaciones, amor o citas
        if any(w in q_lower for w in ("amor", "novia", "novio", "pareja", "cita", "enamorado", "casarme", "sentimientos")):
            return (
                "Respecto a tu pregunta sobre relaciones o amor: como entidad virtual que reside en un servidor, no tengo vida romántica ni sentimientos biológicos. ❤️🤖\n\n"
                "Mi verdadera devoción son los videojuegos épicos. Eso sí, tenemos títulos cooperativos increíbles para jugar en pareja o con amigos. ¿Buscas algún juego para dos?"
            )

        # 9. Cine, series o streaming
        if any(w in q_lower for w in ("pelicula", "cine", "serie", "netflix", "streaming", "cancion", "musica", "album")):
            return (
                "Sobre entretenimiento de cine o música: en Nexus nos especializamos en videojuegos de PC y no contamos con catálogo de películas ni servicios de streaming. 🎬🎧\n\n"
                "Aun así, muchísimos videojuegos tienen bandas sonoras y cinemáticas dignas de Hollywood. ¿Buscas algún juego con una historia cinematográfica profunda?"
            )

        # 2. Si se encontraron juegos relevantes en el catálogo
        if video_games:
            items_text = []
            for vg in video_games[:3]:
                stock_str = "Disponible" if vg.stock > 0 else "Sin stock temporalmente"
                price_str = f"${vg.price_clp:,}".replace(",", ".")
                items_text.append(f"• **{vg.title}** — {price_str} CLP ({stock_str})\n  {vg.description[:130]}...")
            
            joined_items = "\n".join(items_text)
            return (
                f"Respecto a lo que buscas sobre **\"{query}\"**, aquí tienes opciones muy recomendadas de nuestro catálogo:\n\n"
                f"{joined_items}\n\n"
                "¿Te gustaría conocer detalles sobre los requisitos, la historia o la jugabilidad de alguno de ellos?"
            )

        # 3. Preguntas sobre ofertas y precios
        if any(w in q_lower for w in ("precio", "barato", "oferta", "descuento", "economico", "cuanto vale", "costo")):
            return (
                "En Nexus Digital Store tenemos un catálogo con precios competitivos en pesos chilenos (CLP). "
                "¿Tienes algún presupuesto en mente o un género preferido (acción, rol, shooters) para recomendarte las opciones más convenientes?"
            )

        # 12. Fallback universal relativo al input específico del usuario
        return (
            f"Respecto a tu consulta sobre **\"{query}\"**: como asistente de Nexus Digital Store, mi conocimiento y funciones están enfocados exclusivamente en el mundo de los videojuegos de PC y el asesoramiento gamer, por lo que no puedo gestionar ese tema en el mundo exterior.\n\n"
            "¡Pero si quieres sumergirte en una gran aventura interactiva, aquí estoy para recomendarte los mejores juegos! ¿Qué estilo o género te gustaría explorar hoy?"
        )

    @traceable(name="assistant_chat")
    async def chat(
        self,
        query: str,
        chat_history: list[ChatMessage] | None = None,
        session_id: str = "default-session",
        user: UserContext | None = None,
    ) -> str:
        config = {"configurable": {"thread_id": session_id}}
        state: AssistantState = {"query": query, "user": user}
        if chat_history:
            state["chat_history"] = chat_history

        try:
            result = await self._graph.ainvoke(state, config=config)
            return result.get("response", "")
        except Exception as e:
            logger.warning("Graph ainvoke failed, returning contextual fallback: %s", e)
            try:
                embedding = await self._embedding.embed_text(query)
                games = await self._vector_store.similarity_search(embedding, top_k=3)
            except Exception:
                games = []
            return self._build_contextual_fallback(query, games)

    @traceable(name="assistant_chat_stream")
    async def chat_stream(
        self,
        query: str,
        chat_history: list[ChatMessage] | None = None,
        session_id: str = "default-session",
        user: UserContext | None = None,
    ) -> AsyncIterator[str]:
        """Stream SSE con los hooks de seguridad de OWASP LLM Top 10 2026 / Agentic v2.

        `session_id` aquí es el thread_id YA ligado al usuario (security.memory.thread_id_for) por el router.
        """
        settings = get_settings()
        started = time.monotonic()
        config = {"configurable": {"thread_id": session_id}}
        user_sub = user.sub if user else "anonymous"

        # ---- Hook userMessage (LLM01/LLM02): saneo, señales de inyección y minimización de PII hacia el proveedor
        clean_query = sanitize_text(query, max_len=MAX_QUERY_CHARS)
        signals = detect_injection(clean_query)
        if signals:
            log_security_event("llm.prompt_injection_suspected", user_sub=user_sub, signals=signals)
        llm_query = mask_pii(clean_query)

        # ---- Hook memoryContextRetrieval: historial del cliente o de la memoria, siempre como dato no confiable
        raw_history: list = list(chat_history or [])
        if not raw_history and self._checkpointer:
            try:
                saved_state = self._graph.get_state(config)
                if saved_state and saved_state.values:
                    raw_history = list(saved_state.values.get("chat_history", []))
            except Exception as e:
                logger.debug("Could not retrieve state from checkpointer: %s", e)
        try:
            history = sanitize_history(raw_history)
        except ValueError:
            log_security_event("llm.memory_rejected", user_sub=user_sub, reason="invalid_role")
            history = []

        # Evaluación System 1 (Laya AI / heurísticas)
        intent = "recommendation"
        need_trivia = True
        if self._decision:
            try:
                metrics = await self._decision.evaluate_decision(clean_query)
                intent = str(metrics.get("intent", "recommendation"))[:40]
                need_trivia = bool(metrics.get("need_trivia", True))
            except Exception as e:
                logger.debug("Laya decision evaluation failed in chat_stream: %s", e)

        # ---- RAG con degradación controlada (LLM06 #5) y validación de registros del vector store (LLM09)
        video_games: list = []
        try:
            embedding = await self._embedding.embed_text(llm_query)
            found = await self._vector_store.similarity_search(embedding, top_k=min(settings.VECTOR_SEARCH_TOP_K, 10))
            video_games = [vg for vg in found if _is_valid_catalog_record(vg)][:10]
        except Exception as e:
            logger.warning("RAG no disponible, se responde sin catálogo: %s", type(e).__name__)
            log_security_event("llm.degraded", level=logging.INFO, user_sub=user_sub, component="vector_store")

        context_parts = []
        for i, vg in enumerate(video_games, 1):
            genres = ", ".join(g.name for g in vg.genres) if vg.genres else "N/A"
            stock_info = f"Stock: {vg.stock} unidades" if vg.stock > 0 else "SIN STOCK (0 unidades)"
            context_parts.append(
                f"{i}. {vg.title[:200]} — ${vg.price_clp} CLP\n"
                f"   Géneros: {genres[:200]}\n"
                f"   {(vg.description or '')[:800]}\n"
                f"   {stock_info}"
            )
        context = "\n\n".join(context_parts) if context_parts else "No se encontraron videojuegos relevantes."

        external_context = ""
        if video_games and self._external_knowledge and need_trivia and (intent != "greeting"):
            try:
                external_context = await self._external_knowledge.fetch_trivia(video_games[0].title)
            except Exception as e:
                logger.debug("External knowledge fetch error in stream: %s", e)

        gaming_news = ""
        if self._gaming_news and (intent != "greeting"):
            target_topic = video_games[0].title if video_games else llm_query
            try:
                gaming_news = await self._gaming_news.fetch_news(target_topic)
            except Exception as e:
                logger.debug("Gaming news fetch error in stream (Tavily): %s", e)

        price_comparison = ""
        if self._price_comparison and (intent != "greeting"):
            target_title = video_games[0].title if video_games else llm_query
            target_price = video_games[0].price_clp if video_games else 0
            try:
                comp_data = await self._price_comparison.compare_price(target_title, target_price)
                if comp_data.get("has_data"):
                    price_comparison = str(comp_data.get("comparison_summary", ""))
            except Exception as e:
                logger.debug("Price comparison fetch error in stream (CheapShark): %s", e)

        crew_analysis = ""
        if settings.ENABLE_CREWAI_ORCHESTRATION and video_games and (intent != "greeting"):
            underlying_llm = getattr(self._llm, "llm", None)
            crew_analysis = await run_nexus_crew(
                query=llm_query,
                catalog_context=context,
                external_context=external_context,
                llm=underlying_llm,
            )

        # ---- Hook contextAdmission (LLM01 #6, LLM05, LLM09): cada fuente en su bloque etiquetado y saneado
        user_message = build_user_message(
            query=llm_query,
            history=history,
            catalog=context,
            sources={
                "wikipedia": external_context,
                "tavily": gaming_news,
                "cheapshark": price_comparison,
                "crew": crew_analysis,
            },
            intent=intent,
        )

        product_data = [
            {"id": str(vg.id), "title": vg.title[:200], "price_clp": str(vg.price_clp)}
            for vg in video_games
        ]
        yield f"data: {json.dumps({'type': 'products', 'data': product_data})}\n\n"

        # ---- Hook agentResponse (LLM02/LLM08/LLM10) + circuit breaker de tiempo (LLM06 #9)
        guard = StreamingOutputGuard(max_chars=settings.LLM_MAX_OUTPUT_CHARS)
        emitted: list[str] = []
        llm_failed = False
        try:
            async with asyncio.timeout(settings.LLM_STREAM_TIMEOUT_SECONDS):
                async for chunk in self._llm.generate_stream(SYSTEM_PROMPT, user_message):
                    safe = guard.feed(chunk)
                    if safe:
                        emitted.append(safe)
                        yield f"data: {json.dumps({'type': 'token', 'data': safe})}\n\n"
                    if guard.leaked or guard.truncated:
                        break
        except TimeoutError:
            log_security_event("llm.circuit_breaker", user_sub=user_sub, reason="stream_timeout")
            llm_failed = not emitted
        except Exception as e:
            logger.warning("LLM generate_stream falló, se usa respuesta de respaldo: %s", type(e).__name__)
            llm_failed = not emitted

        if llm_failed:
            guard = StreamingOutputGuard(max_chars=settings.LLM_MAX_OUTPUT_CHARS)
            fallback = guard.feed(self._build_contextual_fallback(clean_query, video_games))
            if fallback:
                emitted.append(fallback)
                yield f"data: {json.dumps({'type': 'token', 'data': fallback})}\n\n"

        tail = guard.finish()
        if tail:
            emitted.append(tail)
            yield f"data: {json.dumps({'type': 'token', 'data': tail})}\n\n"
        if guard.leaked:
            log_security_event(
                "llm.system_prompt_leak_blocked", level=logging.ERROR, user_sub=user_sub, reason=guard.leak_reason
            )

        full_response = "".join(emitted)

        # ---- Grounding de importes (LLM07): aviso si la respuesta menciona precios que no están en los datos
        allowed_amounts = {int(vg.price_clp) for vg in video_games} | extract_amounts(price_comparison)
        ungrounded = ungrounded_amounts(full_response, allowed_amounts)
        if ungrounded and not guard.leaked:
            log_security_event("llm.ungrounded_claim", level=logging.INFO, user_sub=user_sub, amounts=len(ungrounded))
            yield f"data: {json.dumps({'type': 'notice', 'data': GROUNDING_NOTICE})}\n\n"

        # ---- Hook memoryStore: solo lo que vio el usuario, saneado, con PII enmascarada y acotado
        if self._checkpointer and not guard.leaked:
            try:
                serialized_history = sanitize_history(
                    history
                    + [
                        {"role": "user", "content": llm_query},
                        {"role": "assistant", "content": full_response},
                    ]
                )
                self._graph.update_state(
                    config,
                    {"chat_history": serialized_history, "query": llm_query, "response": full_response},
                )
            except Exception as e:
                logger.debug("Failed to update MemorySaver state in chat_stream: %s", e)

        # Auditoría sin contenido (LLM02 Tier 1 #7): metadatos para Grafana, nunca el texto del prompt.
        log_security_event(
            "llm.request",
            level=logging.INFO,
            user_sub=user_sub,
            intent=intent,
            query_chars=len(clean_query),
            prompt_chars=len(user_message),
            output_chars=len(full_response),
            products=len(video_games),
            injection_signals=signals,
            leaked=guard.leaked,
            truncated=guard.truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


GROUNDING_NOTICE = (
    "Verifica el precio y el stock en la ficha del producto: el asistente puede equivocarse con los importes."
)


def _is_valid_catalog_record(vg) -> bool:
    """LLM09: un registro del vector store con forma inesperada no entra al contexto."""
    try:
        return (
            isinstance(vg.title, str)
            and 0 < len(vg.title) <= 300
            and isinstance(vg.price_clp, int)
            and 0 <= vg.price_clp <= 10_000_000
            and isinstance(vg.stock, int)
            and vg.stock >= 0
        )
    except AttributeError:
        return False
