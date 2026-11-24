# CLAUDE.md — nexus-backend

Monorepo uv de microservicios (`services/*`) y paquetes compartidos (`packages/nexus-core`, `nexus-security`, `nexus-events`).

## Stack

- Python 3.11+, FastAPI (async en todo el camino de la request).
- SQLAlchemy 2.0 async con `asyncpg`, migraciones con Alembic.
- Base de datos de producción: AWS Aurora PostgreSQL.
- Tests: `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`) + `httpx.AsyncClient`.

## Prioridad entre skills (para evitar conflictos)

- **fastapi-pro**: guía principal para todo el código Python: routers, dependencias, Pydantic v2, SQLAlchemy async, estructura de servicios.
- **senior-backend** (plugin `engineering-skills`): úsala **solo** para optimización de PostgreSQL, diseño de índices, estrategia de migraciones y pruebas de carga. **Ignora sus plantillas y ejemplos de Node/Express**; traduce cualquier recomendación a FastAPI/SQLAlchemy.
- **Superpowers**: manda en el proceso (spec → plan → TDD → revisión).
- **tdd-python**: patrones de pytest/FastAPI dentro del ciclo TDD de Superpowers; si chocan, gana Superpowers en el proceso y este archivo en las reglas técnicas.
- **Trail of Bits** (`static-analysis`, `insecure-defaults`, `property-based-testing`): auditorías de seguridad y tests basados en propiedades (Hypothesis) cuando aplique.

## Flujo obligatorio (SDD + TDD)

1. **Spec primero**: diseña la spec con Superpowers (`brainstorming` → `writing-plans`) antes de tocar código.
2. **TDD estricto Red → Green → Refactor**: ningún código de producción sin un test que falle antes.
   - Endpoints: `httpx.AsyncClient` con `ASGITransport(app=app)`.
   - Tests async con `pytest-asyncio`; nada de `TestClient` síncrono en código nuevo.
3. Verifica (tests en verde, salida real) antes de declarar algo terminado.

## Reglas críticas para AWS Aurora PostgreSQL

### Tests contra PostgreSQL real
- **Nunca** usar SQLite (ni en memoria ni en archivo) para tests.
- Usar PostgreSQL real vía **Testcontainers** (`testcontainers[postgres]`) o el Postgres de `compose.yml`, con la misma versión mayor que Aurora.
- Motivo: respetar tipos nativos, locks, JSONB, constraints y planes de ejecución de Aurora.

### Conexiones Writer / Reader
- Dos engines separados: `writer_engine` (endpoint cluster/Writer) y `reader_engine` (endpoint reader), configurados por variables de entorno distintas.
- Escrituras y lecturas que necesiten read-your-writes → Writer. Lecturas tolerantes a réplica con lag → Reader.
- Ambos engines con:
  - `pool_pre_ping=True`
  - `pool_recycle` (p. ej. 300–1800 s) para descartar conexiones antiguas tras un failover.
  - `pool_size` / `max_overflow` / `pool_timeout` explícitos.
- Las operaciones idempotentes deben poder reintentarse ante errores de conexión cerrada durante un failover.

### Migraciones Alembic zero-downtime
- Toda migración debe ser **compatible hacia atrás**: el código en producción tiene que seguir funcionando con el esquema nuevo (patrón expand → migrate → contract).
- Evitar bloqueos largos de tabla:
  - Índices con `CREATE INDEX CONCURRENTLY` **fuera de transacción** (`with op.get_context().autocommit_block():` + `postgresql_concurrently=True`).
  - Columnas nuevas nullable o con default no volátil; nada de `NOT NULL` sin default sobre tablas grandes en un solo paso.
  - Constraints con `NOT VALID` y luego `VALIDATE CONSTRAINT` en un paso aparte.
  - Nunca renombrar ni borrar columnas/tablas en uso en el mismo despliegue que cambia el código.
  - Fijar `lock_timeout` / `statement_timeout` en las migraciones.
