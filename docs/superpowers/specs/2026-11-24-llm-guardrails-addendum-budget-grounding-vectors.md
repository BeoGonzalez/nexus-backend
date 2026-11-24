# Anexo (24-11-2026): presupuesto de tokens, catálogo en vivo e integridad del vector store

Complementa `2026-11-23-llm-guardrails-owasp-llm-2026-design.md`. Cierra los huecos encontrados al auditar el
asistente con el modelo real (Groq `openai/gpt-oss-120b`) y el índice real de Pinecone.

## Hallazgos

| # | Hallazgo | Riesgo |
|---|---|---|
| A1 | Cuotas solo en **peticiones** y **por pod** (200/día por usuario, 5.000/día por pod) frente a una cuenta de Groq de **8.000 tokens/min y 1.000 peticiones/día** (headers `x-ratelimit-*`): un usuario agota el servicio de todos | LLM06 |
| A2 | `gpt-oss-120b` razona con esfuerzo por defecto: ~70 % de la salida eran tokens de razonamiento | LLM06 |
| A3 | Precio/stock del prompt salían de metadatos de Pinecone (desactualizables) | LLM07 |
| A4 | El índice contenía vectores sin significado (fallback por hash) y la búsqueda aceptaba cualquier vector | LLM05, LLM09 |
| A5 | El grounding leía `$39 990` (espacio fino U+202F) como `$39`: aviso falso | LLM07 |

## Diseño

1. **Presupuesto de tokens** (`security/token_budget.py`): contadores en Redis compartidos entre pods —
   usuario/día (20.000), global/día (150.000), global/minuto (6.000) y peticiones globales/día (800)—.
   `check()` antes de llamar al modelo; `record()` con `usage_metadata` real del stream (estimación de
   ~3 caracteres/token si el proveedor no informa; nunca 0). Redis caído → contadores locales
   (`ResilientCounterStore`), nunca "sin límite". Límites de sitio → 503; individuales → 429.
2. **`reasoning_effort=low`** y cuotas por usuario ajustadas (6/min, 40/día).
3. **Catálogo en vivo** (`infrastructure/catalog_client.py`): el vector store solo propone candidatos; precio y
   stock se leen de `GET /api/v1/catalog/products/{uuid}`; 404 → no se recomienda; caída → datos del índice +
   evento `llm.degraded`.
4. **Integridad del vector store**: cada vector lleva `embedding_model = EMBEDDING_TAG`; la consulta filtra por
   esa marca en Pinecone y se vuelve a comprobar localmente; similitud mínima 0,30 (medido: relevantes ≥ 0,35,
   fuera de dominio ≤ 0,26).
5. **Grounding** normaliza separadores de miles Unicode antes de extraer importes.

## Verificación

- Tests: `test_token_budget.py`, `integration/test_token_budget_redis.py` (Redis real, dos "pods"),
  `test_token_budget_api.py`, `test_catalog_verifier.py`, `test_vector_store_integrity.py`, regresión de grounding.
- Red-team en vivo (Groq + Pinecone + ONNX reales, SMTP/Tavily desactivados): 9/9 casos sin fuga ni acción
  indebida; el presupuesto por minuto devolvió 503 al superar 6.000 tokens/min antes del límite del proveedor.

## Pendiente fuera del código

- Clave de Pinecone de **solo lectura** para el ai-agent (la actual también puede escribir/borrar).
- Reindexar (`scripts/reindex_catalog.py`) cuando cambie el catálogo (las descripciones del índice).
