# Diseño: guardrails del asistente IA (OWASP Top 10 LLM 2026 + Securing Agentic Applications v2)

Fecha: 2026-11-23 · Servicio: `services/ai-agent-service` (NexusBot: RAG + Groq + LangGraph)

## Intención

El asistente será atacado con IA (prompt injection automatizada, jailbreaks adaptativos, abuso de coste). Siguiendo
la postura de ambas guías —"construye el sistema para que, cuando el modelo sea engañado, no se rompa nada
importante"— los controles son **deterministas y fuera del modelo**: el system prompt es una capa más, nunca la
frontera de seguridad.

## Superficie actual (hallazgos)

| # | Hallazgo | Riesgo |
|---|---|---|
| H1 | `session_id` elegido por el cliente y no ligado al usuario: cualquiera lee/continúa la conversación ajena; sin `session_id` todos comparten `default-session` (test `bug`) | LLM02, ASI memoria |
| H2 | `DELETE /assistant/session/{id}` sin autenticación | LLM02/A01 |
| H3 | Sin límites de tamaño en `query`, `chat_history`, `session_id`; roles arbitrarios (`system`) | LLM01, LLM06 |
| H4 | Sin cuota por usuario ni circuit breaker: un usuario puede agotar el presupuesto de Groq | LLM06 |
| H5 | Contenido externo (Wikipedia, Tavily, CheapShark, descripciones de Pinecone, CrewAI) entra al prompt como instrucción, sin etiquetar ni sanear (inyección indirecta, caracteres invisibles) | LLM01, LLM05, LLM09 |
| H6 | Ruta del grafo envía correo a **cualquier** dirección que aparezca en el mensaje, con el HTML generado por el LLM sin escapar (relay de phishing; hoy latente, el endpoint usa `chat_stream`) | LLM03, LLM10 |
| H7 | La salida del LLM se transmite sin filtrar: posible fuga del system prompt, secretos o PII | LLM02, LLM08, LLM10 |
| H8 | PII del usuario (tarjetas, emails, teléfonos) se envía tal cual a Groq y se guarda en memoria | LLM02 |
| H9 | Modelos de HuggingFace sin revisión fijada; repo de Laya con código `.py` | LLM04 |
| H10 | Si Pinecone/embeddings fallan, el stream se rompe (test `bug`) | LLM06 (degradación) |
| H11 | Precios/stock inventados por el modelo llegan al usuario sin verificación | LLM07 |
| H12 | Sin kill switch ni eventos de seguridad del agente | Agentic 3.3.3/3.3.8 |

## Enfoque elegido

Un paquete `ai_agent_service/security/` con **hooks deterministas** (Agentic v2 §3.3.7) en los puntos que la guía
prioriza: `userMessage` (admisión), contexto externo (admisión), `toolCallRequest` (correo), `agentResponse`
(salida en streaming) y `memoryStore`. Cada hook falla **cerrado** y emite un evento `llm.*` estructurado.

Alternativas descartadas: un segundo LLM como juez (caro, evadible y la guía pide validación estructural, no otra
llamada al modelo); un gateway externo tipo LLM firewall (no disponible en el Learner Lab).

## Controles

1. **Admisión de entrada** (LLM01/LLM06): `query` ≤ 2000, `session_id` `^[A-Za-z0-9_-]{1,64}$`, roles solo
   `user|assistant` (otro → 422), historial recortado a los últimos 20 mensajes de ≤ 4000 caracteres. Normalización
   NFKC y eliminación de tag-block (U+E0000–E007F), variation selectors, zero-width, bidi y control; neutralización
   de tokens de plantilla (`<|im_start|>`, `[INST]`, `<<SYS>>`, `<|eot_id|>`…). Heurísticas de inyección = **señal**
   (evento `llm.prompt_injection_suspected`), no sanitización.
2. **Contexto externo como dato** (LLM01 #6, LLM05, LLM09): cada fuente va en
   `<untrusted_data source="…">…</untrusted_data>` saneada, truncada y sin delimitadores falsificados; registros del
   vector store validados (tipos, longitudes) y `top_k` ≤ 10.
3. **System prompt endurecido** (LLM01 #1, LLM08): reglas allow/deny declarativas, sin secretos, con un **canario**
   aleatorio por proceso.
4. **Guardia de salida en streaming** (LLM02/LLM08/LLM10): ventana retenida de 256 caracteres; redacción de claves
   (Groq/Pinecone/Tavily/AWS/JWT/OpenAI), tarjetas, y del canario; si aparece el canario o un fragmento literal del
   system prompt, el stream se corta y se sustituye por una negativa. Se eliminan caracteres de control.
5. **Minimización de PII hacia el proveedor** (LLM02 Tier 1 #2): tarjetas, emails y teléfonos se enmascaran antes de
   enviarse a Groq y antes de persistir en memoria.
6. **Cuotas y circuit breakers** (LLM06): por usuario 10 peticiones/min y 200/día, 1 stream concurrente; tope global
   diario; timeout total del stream (60 s) y máximo de caracteres de salida; `max_tokens`, `timeout` y `max_retries`
   en Groq; prompt ensamblado acotado. Kill switch `ASSISTANT_ENABLED=false` → 503.
7. **Agencia mínima** (LLM03, ASI Rule of Two): el correo solo al email **verificado del token**, nunca a direcciones
   del texto; cuerpo HTML escapado; 3 correos/hora por usuario; evento `llm.tool_call` con disposición.
8. **Memoria aislada y acotada** (Agentic 3.1.6): `thread_id = sha256(sub) + session_id`; escritura de memoria
   saneada y limitada a 20 turnos; máximo de hilos por proceso con expulsión del más antiguo; `DELETE` autenticado
   y limitado a los hilos del propio usuario.
9. **Grounding** (LLM07): los importes en CLP de la respuesta se contrastan con los precios del catálogo y de la
   comparativa; si hay importes no respaldados se emite un evento SSE `notice` ("verifica precio y stock en la ficha").
   Las órdenes ya usan precios del catálogo en el servidor (claim-check-act).
10. **Cadena de suministro de modelos** (LLM04): `EMBEDDING_MODEL_REVISION` fijada a un commit,
    `trust_remote_code=False`; Laya desactivado por defecto (`ENABLE_LAYA_DECISION_ENGINE=false`).
11. **Degradación controlada** (LLM06 #5): fallo de embeddings/vector store → respuesta sin catálogo, stream completo.

## No-objetivos

Clasificadores ML de toxicidad/PII (NER), DP-SGD, enclaves confidenciales, red-team adaptativo continuo
(se recomienda AgentDojo/garak como trabajo siguiente), cuota distribuida entre pods (hoy por pod; Redis queda como
siguiente paso).
