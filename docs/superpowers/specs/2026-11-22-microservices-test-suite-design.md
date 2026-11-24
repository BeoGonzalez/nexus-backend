# Suite de pruebas de los microservicios Nexus — Diseño

Fecha: 2026-11-22 · Rama: `feature/auth`

## Intención

El backend está migrando de monolito (`src/nexus_backend`) a microservicios (`services/*` + `packages/*`) que se desplegarán en **AWS EKS**, cada uno con su imagen y su pipeline. El usuario quiere:

1. Una suite pytest que cubra todos los microservicios y paquetes compartidos.
2. Ejecutarla y saber, con evidencia, si el backend funciona.

Como cada servicio irá a su propio pipeline en EKS, **cada servicio debe poder probarse aislado** (`pytest services/orders-service`).

## Objetivos

- Tests en tres capas por servicio: `unit/`, `api/`, `integration/`.
- Tests para `packages/nexus-core`, `nexus-security`, `nexus-events`.
- Correr la suite completa y por servicio; entregar un informe de qué funciona, qué falla y por qué.

## No-objetivos

- El monolito `src/nexus_backend` y sus tests en `tests/{auth,catalog,orders,ai_assistant}`: se retira. No se toca ni se borra; queda fuera de `testpaths` (ya lo está).
- Arreglar bugs del código de producción. Los tests describen el comportamiento **esperado**; si un test revela un bug, queda en rojo y se reporta.
- Pipelines CI/CD, Helm charts, Alembic, escaneos SAST completos.

## Anti-objetivos (sería un fracaso aunque “pase”)

- Tests que llamen a servicios reales externos: Groq, Pinecone, Tavily, CheapShark, Cognito, Gmail/SMTP, HuggingFace Hub.
- SQLite en cualquier forma (regla de CLAUDE.md).
- Tests que pasan siempre (sin aserciones reales, o que replican la implementación).
- Ajustar los tests al comportamiento actual cuando ese comportamiento es un bug.

## Restricciones

- Python 3.11, pytest + pytest-asyncio (`asyncio_mode=auto`), `httpx.AsyncClient` + `ASGITransport` (CLAUDE.md).
- Integración contra **PostgreSQL 16, Redis 7 y RabbitMQ 3.13** reales vía Testcontainers (mismas versiones que `compose.yml`). Docker 29 está disponible.
- No modificar código de producción. Sí se permite: `pyproject.toml` raíz (deps de dev y config de pytest) y archivos bajo `*/tests/`.
- No hacer commit salvo que el usuario lo pida.

## Enfoques considerados

| | Enfoque | Trade-off |
|---|---|---|
| **A (elegido)** | Suite por servicio en `services/<svc>/tests/{unit,api,integration}` + `packages/<pkg>/tests/` | Más trabajo; requiere Docker para integración. A cambio: cada pipeline EKS prueba su servicio aislado y cumple “Postgres real”. |
| B | Todo centralizado en `tests/` raíz | Fácil de correr junto, pero acopla servicios; mal encaje con pipelines por servicio. |
| C | Solo unitarios con fakes | Rápido, pero no prueba repositorios reales y viola CLAUDE.md. |

El usuario eligió **A**.

## Diseño

### 0. Entorno (prerrequisito)

- El `.venv` actual está desactualizado (no contiene ningún paquete del workspace; `uv run` falla con “trampoline failed”). Se regenera con `uv sync --all-packages --group dev`.
- Se añaden al grupo `dev` del `pyproject.toml` raíz: `testcontainers[postgres,redis,rabbitmq]`, `respx` (mock de httpx), `hypothesis`, `pytest-cov`, `asgi-lifespan` solo si hiciera falta.

### 1. Configuración de pytest (raíz)

- `testpaths = ["packages/*/tests", "services/*/tests", "tests/integration"]`.
- `addopts = "--import-mode=importlib"`: varios servicios tienen `conftest.py`/nombres de test iguales; importlib evita colisiones sin `__init__.py`.
- Marcadores: `integration` (necesita Docker) y `bug` (test que documenta un bug conocido; ver §6). Permite `pytest -m "not integration"` para un ciclo rápido.

### 2. Estructura por servicio

```
services/<svc>/tests/
  conftest.py          # env vars seguras ANTES de importar el servicio; fakes compartidos
  unit/                # dominio + application con fakes de puertos
  api/                 # FastAPI vía httpx.AsyncClient(ASGITransport(app)) + dependency_overrides
  integration/         # adaptadores reales contra contenedores
```

Los tests existentes `test_*_tdd.py` se dejan donde están y se ejecutan tal cual.

**Aislamiento de configuración.** Los routers crean engine/cliente Redis/`CognitoAdapter` al importarse, y las `Settings` tienen defaults peligrosos. El `conftest.py` de cada servicio fija variables de entorno de prueba (URLs a localhost, credenciales vacías) y limpia `get_settings.cache_clear()` antes de importar `main`. `create_async_engine` y `redis.from_url` no conectan al crearse, así que importar es seguro.

**API sin infraestructura.** `ASGITransport` no ejecuta el `lifespan`, así que no se intenta `create_all` ni conectar a RabbitMQ. Se sobrescriben `get_db_session` / `get_*_service` con servicios armados sobre fakes. La identidad se inyecta con un JWT HS256 firmado en el test o con las cabeceras `X-User-*`.

### 3. Cobertura por componente

**packages/nexus-core**: `DatabaseConnectionConfig.normalized_url` (postgres:// → asyncpg, limpieza de `sslmode` etc.; property-based con Hypothesis), `connect_args`, `create_db_engine` aplica `pool_pre_ping`/`pool_recycle`; `JSONFormatter` produce JSON válido con excepción; jerarquía de excepciones; `ApiResponse`/`ErrorResponse`. Integración: `TimestampMixin` contra Postgres (`gen_random_uuid()`, `now()`).

**packages/nexus-security**: `decode_access_token` válido / expirado / firma incorrecta / algoritmo distinto; `get_current_user` con Bearer, sin cabecera, cabeceras `X-User-*`; `require_role` (rol correcto, admin, otro rol → 403).

**packages/nexus-events**: schemas de eventos (serialización round-trip, Hypothesis); `EventPublisher` contra RabbitMQ real: publica en exchange topic `nexus_events` y un consumidor de prueba recibe el mensaje persistente; `close()` idempotente.

**auth-service**: `AuthService` con `IdentityProviderPort` falso (login, register publica `user.registered`, fallo del publisher no rompe el registro, refresh conserva refresh_token, forgot/reset); `CognitoAdapter` con `botocore.stub.Stubber` (nunca AWS real); validaciones de DTOs (password mínima, código de 6 dígitos, email); API: todos los endpoints, `/me` con y sin token, mapeo de `UnauthorizedException` → 401.

**catalog-service**: `CatalogService` (get inexistente → `ResourceNotFoundException`, reserve/release publican el evento correcto, sin publisher no falla); API: listar con paginación y límites, 404, crear requiere admin, 422 por validación; **integración Postgres**: `PostgresCatalogRepository` CRUD, `update_stock` no permite stock negativo, constraints `price_clp > 0` / `stock >= 0`, **concurrencia**: N reservas simultáneas sobre stock limitado nunca dejan stock < 0.

**cart-service**: `Cart`/`CartItem` totales (Hypothesis); `CartService` (producto inexistente, stock insuficiente, sumar a ítem existente, quantity 0 elimina); `HttpCatalogClient` con respx (200, 404, timeout → None); API completa; **integración Redis**: `RedisCartRepository` round-trip, TTL aplicado, `clear`.

**orders-service**: `Order.calculate_total` (Hypothesis); `OrderService.create_order` con catálogo mockeado vía respx (precios del catálogo, no del cliente; stock insuficiente → 409; catálogo caído → 409; producto inexistente → 404), `complete_payment`; API completa; **integración Postgres**: `create` inserta orden + ítems + fila outbox `order.created` en la misma transacción; `mark_paid_and_emit_event` cambia a PAID y añade outbox `order.payment_succeeded`; `idempotency_key` duplicada; constraints. `OutboxWorker` contra Postgres + RabbitMQ reales: publica pendientes y los marca `processed`.

**notifications-service**: handlers con `EmailSenderPort` falso (destinatario = `user_email`, fallback, contenido de boleta, ítems vacíos); `SmtpEmailAdapter` con `aiosmtplib.send` parcheado (nunca SMTP real); consumidor RabbitMQ real enruta `order.created` / `order.payment_succeeded` / `user.registered` al handler correcto; API del router.

**recommendations-service**: `RecommendationService`; `RedisRecommendationStore` contra Redis real (personalizadas, fallback a trending, `limit`, `track_interaction` con zincrby + expire); API `/for-you` (requiere auth) y `/trending`.

**ai-agent-service**: solo la versión por capas (`application/`, `domain/`, `infrastructure/`, `presentation/`). Los módulos duplicados en la raíz del paquete (`services.py`, `graph.py`, `crew.py`, `chains.py`, `dtos.py`) se reportan, no se prueban. `AssistantService` con puertos falsos (LLM, vector store, noticias, precios, decisión, email); adaptadores HTTP (CheapShark, Tavily, Wikipedia) con respx; `LayaDecisionAdapter._heuristic_classify`; `_FallbackEmbedder` determinista; API `/chat` (streaming) con el servicio sobrescrito. **Ojo:** el `model_validator` de `Settings` reemplaza claves de prueba por una clave real de Groq, así que en los tests el LLM siempre se inyecta como fake y nunca se construye `GroqLLMAdapter` real.

### 4. Hallazgos ya identificados que los tests deben cubrir (comportamiento esperado)

Se escriben como tests del comportamiento correcto; si fallan, quedan marcados `@pytest.mark.bug`:

- `GET /api/v1/orders/{id}` y `POST /api/v1/orders/{id}/pay` no exigen autenticación ni verifican que la orden sea del usuario (IDOR).
- `PATCH /api/v1/catalog/products/{id}/stock` no exige autenticación ni rol.
- `CartService.add_item` sobre un ítem existente no verifica stock para la cantidad acumulada; `update_item_quantity` no verifica stock.
- `create_order` con `idempotency_key` repetida debería devolver la orden existente o 409, no un 500.
- Contenido del usuario (`name`, `product_title`) se interpola sin escapar en el HTML de los correos.

### 5. Hallazgos que no se convierten en tests (van al informe)

- **Secretos en el código**: contraseña de aplicación de Gmail en `notifications-service/.../email_adapter.py` y `ai-agent-service/config.py`, y clave de Groq en `ai-agent-service/config.py`. Están en archivos aún no commiteados.
- Defaults inseguros: `JWT_SECRET` por defecto en `nexus_security` y `auth-service`; CORS `*` con credenciales; confianza ciega en cabeceras `X-User-*` (en EKS, cualquier pod del clúster puede suplantar usuarios si no hay NetworkPolicy/mTLS).
- Contra CLAUDE.md: sin engines Writer/Reader separados; `Base.metadata.create_all` en el arranque en vez de migraciones Alembic.
- Código duplicado en `ai-agent-service`.

### 6. Ejecución y reporte

1. `pytest -m "not integration"` (rápido) y `pytest -m integration` (Docker).
2. Cada servicio por separado (`pytest services/<svc>`) para demostrar aislamiento.
3. `pytest --cov` por servicio.
4. Informe final: tabla por servicio (pasan/fallan/bug), causa de cada fallo con salida real, cobertura y los hallazgos de §5.

## Decisiones del constructor (mis llamadas)

- `--import-mode=importlib` en lugar de añadir `__init__.py`.
- respx para HTTP saliente, `botocore.stub.Stubber` para Cognito.
- Contenedores con scope de sesión; limpieza con `TRUNCATE ... CASCADE` / `FLUSHDB` entre tests (los repositorios hacen `commit()`, así que el rollback por test no sirve).
- Marcador `bug` para tests rojos que documentan bugs, filtrables con `-m "not bug"`.
- Sin umbral mínimo de cobertura; se reporta.

## Lo que queda al constructor

- Nombres de archivos de test y fixtures concretos.
- Qué casos Hypothesis valen la pena más allá de los listados.
