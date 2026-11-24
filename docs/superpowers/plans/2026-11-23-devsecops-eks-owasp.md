# DevSecOps EKS + OWASP Top 10:2025 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gates OWASP en CI/CD hacia ECR/EKS (Learner Lab), imágenes/manifiestos endurecidos y app instrumentada para Grafana.

**Architecture:** Hardening transversal en `nexus-core` (logging, telemetría, errores, middleware) y `nexus-security`
(rate limit, fail-closed), cableado en los 7 `main.py` con una sola función. `k8s/` con kustomize, workflow con
matriz por servicio.

**Tech Stack:** FastAPI, OpenTelemetry SDK + OTLP, pytest/httpx, kustomize, GitHub Actions, Trivy, Cosign, Checkov.

**Spec:** `docs/superpowers/specs/2026-11-23-devsecops-eks-owasp-design.md`

## Global Constraints

- Python 3.11; `uv add` para dependencias; nada de SQLite; tests async con `httpx.ASGITransport`.
- Sin commits (el usuario no lo pidió; árbol con trabajo previo sin commitear).
- Nombres/NodePorts k8s idénticos a nexus-infrastructure: auth 30081, catalog 30082, cart 30083, orders 30084,
  notifications 30085, recommendations 30086, ai-agent 30087 (ruta `assistant`).
- Acciones de GitHub fijadas por SHA de 40 caracteres.
- Tests ejecutados con `.venv/Scripts/python.exe -m pytest` (el trampolín de `uv run` falla en esta máquina).

## Review Focus

1. Kubelet probes llegan con `Host: <pod-ip>:8000`: TrustedHost no debe rechazar `/api/v1/*/health`. Test en Task 4.
2. Un 500 dentro de un endpoint SSE (ai-agent) no debe filtrar la traza: cubierto por handler genérico, test en Task 3.
3. Un body de login inválido con `password` no debe ecoarse en el 422. Test en Task 3.
4. `X-Forwarded-For` falsificado no debe permitir saltarse el rate limit rotando IPs para el mismo email. Test en Task 5.
5. Logs con `Authorization: Bearer …` o `password=` en el mensaje deben salir redactados. Test en Task 1.

---

### Task 1: Logging JSON con redacción y correlación de trazas (A09)
**Files:** Modify `packages/nexus-core/src/nexus_core/infrastructure/logging.py`; Test `packages/nexus-core/tests/unit/test_logging.py`
**Produces:** `redact(value: str) -> str`, `RedactingFilter`, `log_security_event(event: str, *, level=logging.WARNING, **fields) -> None` (logger `nexus.security`, campo `security_event`), JSON incluye `trace_id`/`span_id` si hay span activo y campos `extra`.
- [ ] Tests: bearer/JWT/password/secret/api_key redactados; email → `a***@dominio`; evento de seguridad serializado con `security_event` y campos redactados; `trace_id` presente dentro de un span.
- [ ] Rojo → implementar → verde.

### Task 2: Telemetría OpenTelemetry (A09)
**Files:** Create `packages/nexus-core/src/nexus_core/infrastructure/telemetry.py`; Test `packages/nexus-core/tests/unit/test_telemetry.py`
**Produces:** `setup_telemetry(app: FastAPI, service_name: str) -> bool` — False y no-op sin `OTEL_EXPORTER_OTLP_ENDPOINT`; con él: TracerProvider + MeterProvider OTLP (gRPC), `FastAPIInstrumentor.instrument_app`, excluye health.
- [ ] Tests: sin endpoint → False; con endpoint → True y app instrumentada. Deps: `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-instrumentation-fastapi` en nexus-core.

### Task 3: Manejadores globales fail-closed (A10)
**Files:** Create `packages/nexus-core/src/nexus_core/presentation/errors.py`; Test `packages/nexus-core/tests/unit/test_error_handlers.py`
**Produces:** `install_exception_handlers(app: FastAPI) -> None`. ResourceNotFound→404, BusinessRuleViolation→409, Unauthorized→401 (+`WWW-Authenticate`), Forbidden→403, ValidationError/RequestValidationError→422 `{"detail": [{"loc","msg","type"}]}` sin `input`/`ctx`, Exception→500 `{"detail":"Error interno.","request_id":…}` y log con `exc_info`.
- [ ] Tests: 500 sin traza ni SQL; 422 sin eco de password; mapeos de dominio; request_id igual al header `X-Request-ID`.

### Task 4: Middleware de seguridad (A06/A09)
**Files:** Create `packages/nexus-core/src/nexus_core/presentation/security.py`; Test `packages/nexus-core/tests/unit/test_security_middleware.py`
**Produces:** `SecuritySettings` (lee env: `CORS_ALLOWED_ORIGINS`, `ALLOWED_HOSTS`, `ENABLE_HSTS`=true), `install_security_middleware(app, settings: SecuritySettings | None = None)`, `configure_service(app, service_name) -> None` (= errors + security + telemetry). Cabeceras: HSTS `max-age=63072000; includeSubDomains`, CSP `default-src 'none'; frame-ancestors 'none'`, nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `X-Request-ID`. Log de seguridad para 401/403/429.
- [ ] Tests: cabeceras presentes; CORS no refleja origen no permitido y sí el permitido; Host no permitido → 400 salvo `/health`; 401 genera evento `http.unauthorized`.

### Task 5: Rate limit y verify_token fail-closed (A07)
**Files:** Create `packages/nexus-security/src/nexus_security/rate_limit.py`; Modify `dependencies.py`, `services/auth-service/.../presentation/router.py`; Tests `packages/nexus-security/tests/unit/test_rate_limit.py`, `test_dependencies.py`, `services/auth-service/tests/api/test_auth_rate_limit.py`
**Produces:** `SlidingWindowRateLimiter(max_requests:int, window_seconds:float)`, `.hit(key:str)->bool`, `rate_limit(limiter, scope:str)` dependencia que usa IP del peer + email del body → 429 con `Retry-After` y evento `auth.rate_limited`. Login: 5/60 s por email y 20/60 s por IP.
- [ ] Tests: 6º login mismo email → 429 aunque cambie XFF; sin `JWT_SECRET` ni Cognito → 401.

### Task 6: Cableado en los 7 servicios + docs off
**Files:** Modify `services/*/src/*/main.py`; Test `tests/security/test_service_hardening.py` (añadir `tests/security` a testpaths)
- [ ] Test parametrizado por app: cabeceras, `/docs` → 404, ruta inexistente sin traza.

### Task 7: Dockerfiles endurecidos, .dockerignore, .gitignore (A02/A08/A04)
### Task 8: `k8s/` kustomize + NetworkPolicy + secret.example (A01/A02)
### Task 9: Workflow `.github/workflows/devsecops-eks.yml` (A01–A08), configs `.gitleaks.toml`, `.hadolint.yaml`, `.checkov.yaml`
### Task 10: `observability/grafana-eks-security-alerts.yaml` (A09)
### Task 11: Verificación: pytest, `kubectl kustomize k8s`, parseo YAML, hadolint/checkov locales si están disponibles.
