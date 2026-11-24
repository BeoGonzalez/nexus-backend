# Suite de pruebas de microservicios Nexus — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suite pytest en tres capas (unit / api / integration) para los 7 microservicios y los 3 paquetes compartidos, ejecutada completa y por servicio, con informe final.

**Architecture:** Cada servicio tiene `tests/{unit,api,integration}` y su `conftest.py`; los contenedores (Postgres/Redis/RabbitMQ) son fixtures de sesión en un `conftest.py` raíz. Las capas `api` usan `httpx.AsyncClient(transport=ASGITransport(app=app))` + `app.dependency_overrides` con fakes de puertos.

**Tech Stack:** Python 3.11, pytest 9, pytest-asyncio (auto), httpx, respx, hypothesis, testcontainers, pytest-cov, botocore Stubber.

**Spec:** `docs/superpowers/specs/2026-11-22-microservices-test-suite-design.md`

## Naturaleza del TDD en este plan

El código de producción ya existe y **no se modifica**. Cada test codifica el comportamiento *esperado* según el spec. Ciclo por test:
1. Escribir el test → 2. Ejecutarlo → 3a. PASA: el comportamiento es correcto. Verificar que el test es significativo rompiendo temporalmente la aserción (no el código) y viendo el rojo. → 3b. FALLA: decidir si el test está mal (corregir el test) o el código tiene un bug (marcar `@pytest.mark.bug(reason="...")` y dejarlo rojo).

Nunca se ajusta una aserción para que coincida con un bug.

## Global Constraints

- Nunca SQLite. Postgres `postgres:16-alpine`, Redis `redis:7-alpine`, RabbitMQ `rabbitmq:3.13-management-alpine` vía Testcontainers.
- Nunca llamar a Groq, Pinecone, Tavily, CheapShark, Wikipedia, Cognito/AWS, SMTP/Gmail ni HuggingFace Hub reales.
- Solo se crean/modifican: `pyproject.toml` raíz, `conftest.py` raíz, y archivos bajo `services/*/tests/` y `packages/*/tests/`. Cero cambios en `src/`.
- Sin commits (el usuario hace commit cuando lo pida).
- Tests async sin decorador (`asyncio_mode = "auto"`); nada de `TestClient` síncrono.
- No probar los módulos duplicados en la raíz de `ai_agent_service` (`services.py`, `graph.py`, `crew.py`, `chains.py`, `dtos.py`).
- No imprimir ni copiar secretos encontrados en el código en tests ni en el informe.

## Review Focus

1. **Settings que filtran infraestructura real al importar**: un test que importe `main` sin el `conftest` del servicio no debe abrir conexiones; cada `conftest.py` de servicio fija env vars y hace `get_settings.cache_clear()` antes de importar. Test: `test_app_imports_without_network` en cada `api/`.
2. **Groq real por el `model_validator`**: `ai_agent_service.config.Settings` reemplaza claves dummy por una real. Test en Task 11: `test_chat_never_builds_real_llm` parchea `GroqLLMAdapter.__init__` para fallar si se invoca durante los tests de API.
3. **Concurrencia de stock**: reservas simultáneas no dejan stock negativo. Test en Task 6: `test_concurrent_reservations_never_oversell`.
4. **Estado compartido entre tests de integración**: los repositorios hacen `commit()`. Fixture autouse de limpieza (`TRUNCATE ... CASCADE`, `FLUSHDB`) en cada `integration/conftest.py`. Test en Task 6: `test_db_is_clean_between_tests` (dos tests que crean el mismo título y cuentan 1).
5. **Contenido de usuario en HTML de correos**: `name` / `product_title` con `<script>` deben llegar escapados. Tests en Task 9 (`bug` si fallan).

---

### Task 1: Entorno, configuración de pytest y fixtures de contenedores

**Files:**
- Modify: `pyproject.toml` (grupo `dev`, `[tool.pytest.ini_options]`)
- Create: `conftest.py` (raíz)
- Create: `packages/nexus-core/tests/test_smoke_infra.py`

**Interfaces:**
- Produces (fixtures de sesión en `conftest.py` raíz):
  - `postgres_url() -> str` — URL `postgresql+asyncpg://...` de un contenedor Postgres 16.
  - `redis_url() -> str` — `redis://host:port/0`.
  - `rabbitmq_url() -> str` — `amqp://guest:guest@host:port/`.
  - `make_token(sub: str = "user-1", email: str | None = "buyer@nexus.cl", role: str = "customer", exp_delta_s: int = 3600, secret: str = TEST_JWT_SECRET) -> str` — fixture función que firma HS256.
  - Constante `TEST_JWT_SECRET = "test-secret-not-for-prod"`; el conftest fija `os.environ["JWT_SECRET"] = TEST_JWT_SECRET` al cargar.
  - Los contenedores se omiten (`pytest.skip`) con mensaje claro si Docker no está disponible.

- [ ] **Step 1:** Añadir al grupo `dev`: `testcontainers[postgres,redis,rabbitmq]>=4.8`, `respx>=0.21`, `hypothesis>=6.100`, `pytest-cov>=5`.
- [ ] **Step 2:** `[tool.pytest.ini_options]`: `testpaths = ["packages/*/tests", "services/*/tests", "tests/integration"]`, `addopts = "--import-mode=importlib -ra"`, `markers = ["integration: requiere Docker", "bug(reason): documenta un bug conocido del código de producción"]`, mantener `asyncio_mode = "auto"`; añadir `asyncio_default_fixture_loop_scope = "session"` y `asyncio_default_test_loop_scope = "session"` (fixtures async de sesión).
- [ ] **Step 3:** `uv sync --all-packages --group dev` (recrear `.venv` si `uv run` sigue fallando con "trampoline"). Expected: `uv run python -c "import orders_service, cart_service, auth_service, nexus_core, testcontainers"` sin error.
- [ ] **Step 4:** Escribir `conftest.py` raíz con las fixtures de arriba. En `integration`, marcar automáticamente con `pytest.mark.integration` todo test bajo un directorio `integration/` (hook `pytest_collection_modifyitems`).
- [ ] **Step 5:** Test de humo `test_postgres_container_answers` (`SELECT 1` vía `create_async_engine(postgres_url)` == 1) y `test_make_token_roundtrip` (`jwt.decode(make_token(), TEST_JWT_SECRET, ["HS256"])["sub"] == "user-1"`).
- [ ] **Step 6:** `uv run pytest packages/nexus-core/tests/test_smoke_infra.py -v` → 2 passed.

### Task 2: nexus-core

**Files:** Create `packages/nexus-core/tests/unit/test_database_config.py`, `unit/test_logging.py`, `unit/test_exceptions_and_dtos.py`, `integration/test_timestamp_mixin.py`

- [ ] **Step 1: tests de `DatabaseConnectionConfig`**
  - `test_postgres_scheme_normalized`: `"postgres://u:p@h/db"` → `"postgresql+asyncpg://u:p@h/db"`; idem `postgresql://`.
  - `test_strips_libpq_only_params`: `...?sslmode=require&channel_binding=x&application_name=nexus` → query == `application_name=nexus`.
  - `test_asyncpg_url_untouched`.
  - `test_connect_args_ssl`: `ssl=True` → `{"ssl": "require"}`; `False` → `{}`.
  - `test_engine_applies_pool_settings`: `create_db_engine(cfg)` → `engine.pool._pre_ping is True`, `engine.pool._recycle == 1800`.
  - Hypothesis `test_normalized_url_idempotent`: `normalize(normalize(x)) == normalize(x)` para hosts/db alfanuméricos y combinaciones de params.
- [ ] **Step 2: logging** — `test_json_formatter_valid_json` (campos `level`, `logger`, `message`), `test_json_formatter_includes_exception`, `test_setup_service_logging_single_handler` (llamar dos veces → 1 handler).
- [ ] **Step 3: excepciones/DTOs** — `.message` se conserva; subclases de `DomainException`; `ApiResponse[int](data=1).success is True`; `ErrorResponse(detail="x").success is False`.
- [ ] **Step 4: integración** — modelo de prueba `_Probe(TimestampMixin, Base)` en metadata propia del test; insert sin `id` → UUID generado; `created_at` tz-aware.
- [ ] **Step 5:** `uv run pytest packages/nexus-core -v` → todo verde o `bug` justificados.

### Task 3: nexus-security

**Files:** Create `packages/nexus-security/tests/unit/test_jwt.py`, `unit/test_dependencies.py`, `unit/test_permissions.py`

**Interfaces:** Consumes `make_token`, `TEST_JWT_SECRET` (Task 1).

- [ ] **Step 1:** `decode_access_token`: válido → `TokenPayload(sub=..., role="customer")`; expirado (`exp_delta_s=-10`) → `UnauthorizedException` con "expirado"; firma con otro secreto → `UnauthorizedException` "inválido"; token `alg=none` → `UnauthorizedException`.
- [ ] **Step 2:** `get_current_user` vía mini-app FastAPI con un endpoint `GET /who` que devuelve el payload, probada con `httpx.AsyncClient`: Bearer válido → 200 `sub`; sin cabecera → 401; `Basic xxx` → 401; token expirado → 401; `X-User-Id: u9` + `X-User-Role: admin` → 200 con `role == "admin"` (documenta la confianza en cabeceras; no es `bug`, va al informe).
- [ ] **Step 3:** `require_role("admin")`: customer → 403; admin → 200. `require_role("editor")`: admin → 200 (admin pasa siempre).
- [ ] **Step 4:** `uv run pytest packages/nexus-security -v`.

### Task 4: nexus-events

**Files:** Create `packages/nexus-events/tests/unit/test_schemas.py`, `integration/test_publisher.py`

- [ ] **Step 1:** Leer `nexus_events/schemas/{orders,catalog,users}.py`; por cada evento, test Hypothesis `test_<event>_json_roundtrip`: `Model.model_validate_json(m.model_dump_json()) == m`.
- [ ] **Step 2:** `test_publish_reaches_bound_queue` (RabbitMQ real): declarar cola exclusiva enlazada a `nexus_events` con `user.registered`; `EventPublisher(rabbitmq_url).publish("user.registered", UserRegisteredEvent(...))`; recibir en ≤5 s; `delivery_mode == PERSISTENT`, `content_type == "application/json"`, body igual al dump.
- [ ] **Step 3:** `test_close_is_idempotent` (dos `close()` sin error) y `test_publish_reconnects_after_close`.
- [ ] **Step 4:** `uv run pytest packages/nexus-events -v`.

### Task 5: auth-service

**Files:** Create `services/auth-service/tests/conftest.py`, `unit/test_auth_service.py`, `unit/test_dtos.py`, `unit/test_cognito_adapter.py`, `api/test_auth_api.py`

**Interfaces:**
- Produces (conftest): `FakeIdentityProvider(IdentityProviderPort)` con atributos `calls: list[tuple[str, tuple]]` y comportamiento configurable (`fail_with: Exception | None`); `FakePublisher` con `published: list[tuple[str, BaseModel]]` y `fail: bool`; fixture `client` (AsyncClient con `get_auth_service` sobrescrito).
- conftest fija antes de importar: `RABBITMQ_URL=""`, `COGNITO_USER_POOL_ID=""`, `COGNITO_APP_CLIENT_ID=""`, `DATABASE_URL=postgresql+asyncpg://x:x@localhost:1/x`.

- [ ] **Step 1: service** — `test_login_maps_tokens`; `test_register_publishes_user_registered` (routing key `"user.registered"`, email); `test_register_survives_publisher_failure`; `test_refresh_keeps_old_refresh_token_when_absent`; `test_reset_password_forwards_code`.
- [ ] **Step 2: DTOs** — password < 8 en register → `ValidationError`; código de confirmación de 5 o 7 chars → error; email inválido → error.
- [ ] **Step 3: CognitoAdapter** — leer `infrastructure/cognito.py` completo; parchear `CognitoAdapter._get_client` para devolver `boto3.client("cognito-idp", region_name="us-east-1")` envuelto en `botocore.stub.Stubber`; cubrir `authenticate` (`initiate_auth` → tokens), credenciales inválidas (`NotAuthorizedException` → la excepción de dominio que el adaptador defina), `register` (`sign_up`), y la ruta "no configurado" (comportamiento local que defina el adaptador). Si el adaptador calcula `SECRET_HASH`, verificar el parámetro enviado.
- [ ] **Step 4: API** — `test_app_imports_without_network`; `/login` 200 y 422; `/register` 201; `/confirm`; `/resend-code?email=`; `/refresh`; `/forgot-password`; `/reset-password`; `/me` con token → 200 y sin token → 401; `/info` no expone secretos (`has_client_secret` es bool); `/health` 200; `UnauthorizedException` desde el IdP → 401.
- [ ] **Step 5:** `uv run pytest services/auth-service -v` (incluye `test_auth_tdd.py` existente).

### Task 6: catalog-service

**Files:** Create `services/catalog-service/tests/conftest.py`, `unit/test_catalog_service.py`, `api/test_catalog_api.py`, `integration/conftest.py`, `integration/test_catalog_repository.py`

**Interfaces:**
- Produces: `InMemoryCatalogRepository(CatalogRepositoryPort)` (stock nunca negativo en `update_stock`); `FakePublisher`; `integration/conftest.py`: fixture `session_factory(postgres_url)` que hace `create_all` una vez y fixture autouse `TRUNCATE products, genres, platforms, product_genres CASCADE`.

- [ ] **Step 1: service** — get inexistente → `ResourceNotFoundException`; `reserve_stock` exitoso publica `"catalog.stock_reserved"`; sin stock publica `"catalog.stock_reservation_failed"` y retorna `False`; `release_stock` publica `"catalog.stock_released"`; `publisher=None` no falla.
- [ ] **Step 2: API** — listar (skip/limit; `limit=101` → 422); get 404; crear con token admin → 201; con customer → 403; sin token → 401; `price_clp=0` → 422; `test_update_stock_requires_admin` (`PATCH .../stock` sin token debe dar 401) → esperado rojo, marcar `bug("PATCH stock sin autenticación")`.
- [ ] **Step 3: integración** — `create`/`get_by_id`/`get_all` paginado; `update_stock(-n)` más allá del stock → `False` y stock intacto; insertar `price_clp=0` directo → `IntegrityError`; `test_concurrent_reservations_never_oversell`: stock 5, 20 tareas `asyncio.gather` con sesiones distintas haciendo `update_stock(id, -1)` → exactamente 5 `True`, stock final 0; `test_db_is_clean_between_tests` (×2).
- [ ] **Step 4:** `uv run pytest services/catalog-service -v`.

### Task 7: cart-service

**Files:** Create `services/cart-service/tests/conftest.py`, `unit/test_cart_domain.py`, `unit/test_cart_service.py`, `unit/test_catalog_client.py`, `api/test_cart_api.py`, `integration/test_redis_cart_repository.py`

**Interfaces:** Produces `InMemoryCartRepository`, `FakeCatalogClient(products: dict[uuid.UUID, dict])`.

- [ ] **Step 1: dominio** — Hypothesis: `total_amount_clp == Σ price*qty`, `total_items_count == Σ qty`, carrito vacío → 0.
- [ ] **Step 2: service** — producto inexistente → 404 domain; stock < qty → `BusinessRuleViolationException`; agregar dos veces suma cantidades; `quantity=0` elimina; actualizar ítem ausente → `ResourceNotFoundException`; `test_add_existing_item_respects_stock` (stock 3, agregar 2 + 2 → debe fallar) → `bug`; `test_update_quantity_respects_stock` → `bug`.
- [ ] **Step 3: HttpCatalogClient** con respx (`CATALOG_SERVICE_URL=http://catalog.test`): 200 → dict; 404 → `None`; `httpx.ConnectTimeout` → `None`.
- [ ] **Step 4: API** — todas las rutas con y sin token; `quantity=0` en POST → 422; DELETE → 204.
- [ ] **Step 5: integración Redis** — round-trip conserva ítems y UUIDs; `TTL cart:<user>` ≈ `CART_TTL_SECONDS` (±5 s); `clear` borra la clave; usuario sin carrito → `Cart` vacío.
- [ ] **Step 6:** `uv run pytest services/cart-service -v`.

### Task 8: orders-service

**Files:** Create `services/orders-service/tests/conftest.py`, `unit/test_order_domain.py`, `unit/test_order_service.py`, `api/test_orders_api.py`, `integration/conftest.py`, `integration/test_order_repository.py`, `integration/test_outbox_worker.py`

**Interfaces:** Consumes `postgres_url`, `rabbitmq_url`, `make_token`. Produces `InMemoryOrderRepository` (puede reutilizar el de `test_orders_tdd.py` copiándolo al conftest; no importar entre archivos de test).

- [ ] **Step 1: dominio** — Hypothesis: `calculate_total` == Σ subtotales; `subtotal_clp == price*qty`.
- [ ] **Step 2: service** (respx sobre `CATALOG_SERVICE_URL=http://catalog.test`) — usa `price_clp` del catálogo; stock insuficiente → `BusinessRuleViolationException`; catálogo 404 → `ResourceNotFoundException`; `httpx.ConnectError` → `BusinessRuleViolationException`; `complete_payment` inexistente → `ResourceNotFoundException`.
- [ ] **Step 3: API** — POST 201 (orden con `user_id == token.sub` y `user_email`); items vacíos → 422; GET lista solo las del usuario; GET por id inexistente → 404; `test_get_other_users_order_forbidden` (usuario B pide orden de A → 403/404) → `bug("IDOR")`; `test_get_order_requires_auth` → `bug`; `test_pay_requires_auth` y `test_pay_other_users_order_forbidden` → `bug`; regla de negocio → 409.
- [ ] **Step 4: integración repo** — `create` inserta orden, ítems y 1 fila outbox `order.created` cuyo `payload_json` tiene `order_id`, `user_email`, `total_amount_clp`; `mark_paid_and_emit_event` → status `PAID` en DB + fila outbox `order.payment_succeeded` con `payment_id`; inexistente → `None`; `test_duplicate_idempotency_key_returns_existing_or_conflict` (segunda creación con misma clave no debe lanzar `IntegrityError` crudo) → `bug` si falla; `quantity=0` directo → `IntegrityError`.
- [ ] **Step 5: integración outbox** — insertar 2 eventos pendientes; correr `OutboxWorker.start()` como tarea, esperar hasta que ambos estén `processed` (timeout 10 s), cancelar; una cola de prueba enlazada a `order.#` recibe 2 mensajes con routing keys correctas.
- [ ] **Step 6:** `uv run pytest services/orders-service -v`.

### Task 9: notifications-service

**Files:** Create `services/notifications-service/tests/conftest.py`, `unit/test_handlers.py`, `unit/test_smtp_adapter.py`, `api/test_notifications_api.py`, `integration/test_rabbitmq_consumer.py`

**Interfaces:** Produces `FakeEmailSender` con `sent: list[tuple[recipient, subject, html]]`. conftest fija `SMTP_USER=""`, `SMTP_PASSWORD=""`.

- [ ] **Step 1: handlers** — order_created usa `user_email`; sin email → `<user_id>@nexus-store.cl`; payment_succeeded incluye `payment_id`, total formateado `"$29,990 CLP"` y una fila por ítem; ítems vacíos → fila genérica; user_registered usa `full_name` o "Gamer"; `test_product_title_is_html_escaped` y `test_user_name_is_html_escaped` (`<script>` no aparece literal) → `bug` si fallan.
- [ ] **Step 2: SmtpEmailAdapter** — parchear `aiosmtplib.send` (AsyncMock): con `SMTP_USER`/`SMTP_PASSWORD` de prueba envía con `start_tls=True` y retorna `True`; si `send` lanza → `False`; `test_no_hardcoded_credentials_fallback`: con ambos vacíos **no** debe llamar a `aiosmtplib.send` (modo mock) → `bug` si llama (hoy cae a credenciales embebidas).
- [ ] **Step 2b:** Leer `presentation/router.py` (236 líneas) y escribir tests de cada endpoint con el handler/sender sobrescritos.
- [ ] **Step 3: integración** — arrancar `NotificationsRabbitConsumer(rabbitmq_url, handler_con_FakeEmailSender)` como tarea; publicar `order.created`, `order.payment_succeeded`, `user.registered`; esperar 3 envíos (timeout 10 s) con destinatarios correctos; cancelar tarea.
- [ ] **Step 4:** `uv run pytest services/notifications-service -v`.

### Task 10: recommendations-service

**Files:** Create `services/recommendations-service/tests/conftest.py`, `unit/test_recommendation_service.py`, `api/test_recommendations_api.py`, `integration/test_redis_store.py`

- [ ] **Step 1:** service delega con `limit`.
- [ ] **Step 2: API** — `/for-you` sin token → 401, con token → 200; `/trending` público; `limit=21` → 422.
- [ ] **Step 3: Redis** — `recommendations:<user>` presente → esas, cortadas a `limit`; ausente → trending; trending ausente → fallback de 2 ítems; `track_interaction` → `ZSCORE affinity:<u> <pid>` == peso acumulado y `TTL` > 0.
- [ ] **Step 4:** `uv run pytest services/recommendations-service -v`.

### Task 11: ai-agent-service

**Files:** Create `services/ai-agent-service/tests/conftest.py`, `unit/test_assistant_service.py`, `unit/test_http_adapters.py`, `unit/test_laya_heuristics.py`, `unit/test_fallback_embedder.py`, `api/test_ai_api.py`

**Interfaces:** Produces fakes que cumplen los `Protocol` de `domain/ports.py`: `FakeLLM` (respuestas fijas + stream de chunks), `FakeVectorStore`, `FakeNews`, `FakePrices`, `FakeDecision(intent: str)`, `FakeEmail`. conftest fija `PINECONE_API_KEY=""`, `TAVILY_API_KEY=""`, `LANGCHAIN_TRACING_V2=false` y parchea `GroqLLMAdapter.__init__`, `PineconeVectorStoreAdapter.__init__` para lanzar `AssertionError("real adapter built in tests")`.

- [ ] **Step 1:** Leer `application/services.py`, `graph.py`, `crew.py`, `presentation/router.py` completos; mapear qué intenciones (`classify_intent`) existen y qué puerto usa cada una.
- [ ] **Step 2: AssistantService** — una prueba por intención verificando que se consulta el puerto correcto y la respuesta incluye su contenido; `_build_contextual_fallback` con lista vacía y con juegos; fallo del LLM → fallback (no excepción); `chat_stream` emite chunks en orden.
- [ ] **Step 3: adaptadores HTTP** con respx — CheapShark (juego encontrado, no encontrado, timeout), Tavily (sin API key, OK, error 500), Wikipedia (parchear la librería).
- [ ] **Step 4:** `LayaDecisionAdapter._heuristic_classify` con una consulta representativa por intención; `_FallbackEmbedder.embed_query` determinista y de longitud 384.
- [ ] **Step 5: API** — `test_chat_never_builds_real_llm`; `/chat` con servicio sobrescrito devuelve stream con los chunks; `/session/{id}` DELETE; `/health`.
- [ ] **Step 6:** `uv run pytest services/ai-agent-service -v`.

### Task 12: Ejecución completa e informe

- [ ] **Step 1:** `uv run pytest -m "not integration" -q` → registrar totales.
- [ ] **Step 2:** `uv run pytest -m integration -q` → registrar totales.
- [ ] **Step 3:** Por cada servicio y paquete: `uv run pytest <ruta> -q --cov=<modulo> --cov-report=term` → aislamiento demostrado y cobertura.
- [ ] **Step 4:** Incluir `tests/integration/test_purchase_flow_sdd.py` y los `test_*_tdd.py` existentes en el conteo.
- [ ] **Step 5:** Informe al usuario: tabla servicio × (passed / failed / bug / skipped / cobertura), cada `bug` con el comando para reproducirlo, fallos no-bug con salida real, y hallazgos §5 del spec.
