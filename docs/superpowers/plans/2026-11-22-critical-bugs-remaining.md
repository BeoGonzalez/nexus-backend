# Bugs críticos restantes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar el modo local fail-open de auth-service y el relay de `/send-receipt`, y hacer que el proxy del frontend reenvíe el token.

**Architecture:** Auth local queda tras un flag explícito con contraseñas scrypt, admins por lista y refresh tokens emitidos en memoria. `/send-receipt` envía solo al email del JWT. El BFF reutiliza `buildForwardHeaders`.

**Tech Stack:** FastAPI, pydantic-settings, stdlib `hashlib.scrypt`/`hmac`/`secrets`, PyJWT, pytest + httpx ASGITransport; Next.js route + vitest.

**Spec:** `docs/superpowers/specs/2026-11-22-critical-bugs-remaining-design.md`

## Global Constraints

- Sin dependencias nuevas (scrypt de la stdlib).
- `AUTH_LOCAL_MODE` por defecto `false`; `LOCAL_ADMIN_EMAILS` por defecto `""` (lista separada por comas).
- Sin Cognito y sin flag → `UnauthorizedException`; nunca emitir tokens.
- `/send-receipt`: destinatario = email del token; sin email en token → 403; `customer_email` distinto (case-insensitive) → 403.
- No commitear (el usuario no lo ha pedido; árbol con cambios de otra sesión). Los pasos "commit" se omiten.
- Correr pytest con `uv run python -m pytest`.

## Review Focus

1. Email con mayúsculas/espacios distintos entre registro y login (`Ana@B.cl ` vs `ana@b.cl`) → debe autenticar igual. Test en Task 1.
2. Registrar dos veces el mismo email en modo local no debe sobrescribir la contraseña del primero → `BusinessRuleViolationException` ("Ya existe"), igual que Cognito. Test en Task 1.
3. Refresh token reutilizado tras emitir uno nuevo: se acepta mientras viva el proceso (modo dev, sin rotación); no se prueba, decisión explícita.
4. `/send-receipt` con `customer_email` en mayúsculas igual al del token → 200. Test en Task 2.
5. Proxy de boleta sin token ni cookie → no inventa cabecera; el backend responde 401 y el proxy propaga el status. Test en Task 3.

---

### Task 1: Auth local fail-closed

**Files:**
- Modify: `services/auth-service/src/auth_service/config.py` (añadir `AUTH_LOCAL_MODE: bool = False`, `LOCAL_ADMIN_EMAILS: str = ""`)
- Modify: `services/auth-service/src/auth_service/infrastructure/cognito.py` (sección local, `authenticate`/`register`/`refresh_tokens`)
- Modify: `conftest.py` raíz (`_INERT_ENV["AUTH_LOCAL_MODE"] = "true"`)
- Modify: `compose.yml` (auth-service: `AUTH_LOCAL_MODE=${AUTH_LOCAL_MODE:-true}`, `LOCAL_ADMIN_EMAILS=${LOCAL_ADMIN_EMAILS:-}`)
- Test: `services/auth-service/tests/unit/test_cognito_adapter.py`; ajustar `services/auth-service/tests/test_auth_tdd.py::test_auth_fastapi_endpoints` (hoy hace login sin registrarse: debe registrar primero por el endpoint de registro).

**Interfaces:**
- Produces: `CognitoAdapter.local_mode_enabled -> bool` (`settings.AUTH_LOCAL_MODE`); `_hash_password(password: str, salt: bytes | None = None) -> str` y `_verify_password(password: str, stored: str) -> bool` (formato `scrypt$<salt_hex>$<hash_hex>`, n=2**14, r=8, p=1); `self._local_refresh_tokens: dict[str, str]` (token → email normalizado).

- [ ] **Step 1: Tests nuevos (RED)** en `test_cognito_adapter.py`. El fixture `local_adapter` sigue igual (el entorno de tests ya trae el flag). Añadir:

```python
@pytest.fixture
def unconfigured_adapter(monkeypatch):
    adapter = CognitoAdapter()
    adapter.settings = Settings(AUTH_LOCAL_MODE=False)
    return adapter

async def test_without_cognito_or_local_flag_login_fails_closed(unconfigured_adapter):
    with pytest.raises(UnauthorizedException):
        await unconfigured_adapter.authenticate("ana@b.cl", "pw123456")

async def test_without_cognito_or_local_flag_register_fails_closed(unconfigured_adapter):
    with pytest.raises(UnauthorizedException):
        await unconfigured_adapter.register("ana@b.cl", "pw123456", "Ana")

async def test_local_mode_rejects_unregistered_user(local_adapter):
    with pytest.raises(UnauthorizedException):
        await local_adapter.authenticate("ghost@b.cl", "pw123456")

async def test_local_mode_grants_admin_only_to_listed_emails(local_adapter):
    local_adapter.settings = Settings(AUTH_LOCAL_MODE=True, LOCAL_ADMIN_EMAILS="boss@nexus.cl, other@nexus.cl")
    await local_adapter.register("boss@nexus.cl", "pw123456", "Boss")
    claims = jwt.decode((await local_adapter.authenticate("boss@nexus.cl", "pw123456"))["access_token"],
                        TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["role"] == "admin"

async def test_local_mode_refresh_accepts_issued_token(local_adapter):
    await local_adapter.register("ana@b.cl", "pw123456", "Ana")
    tokens = await local_adapter.authenticate("ana@b.cl", "pw123456")
    refreshed = await local_adapter.refresh_tokens(tokens["refresh_token"], "ana@b.cl")
    assert jwt.decode(refreshed["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])["email"] == "ana@b.cl"

async def test_local_mode_email_is_case_and_space_insensitive(local_adapter):
    await local_adapter.register("Ana@B.cl ", "pw123456", "Ana")
    assert (await local_adapter.authenticate("ana@b.cl", "pw123456"))["access_token"]

async def test_local_mode_duplicate_register_is_rejected(local_adapter):
    await local_adapter.register("ana@b.cl", "pw123456", "Ana")
    with pytest.raises(BusinessRuleViolationException, match="Ya existe"):
        await local_adapter.register("ana@b.cl", "other-pass", "Eve")

def test_password_hash_is_salted_and_verifiable():
    from auth_service.infrastructure.cognito import _hash_password, _verify_password
    a, b = _hash_password("pw123456"), _hash_password("pw123456")
    assert a != b and "pw123456" not in a
    assert _verify_password("pw123456", a) and not _verify_password("nope", a)
```

- [ ] **Step 2: Correr y ver fallar.** `uv run python -m pytest services/auth-service/tests/unit/test_cognito_adapter.py -q -p no:cacheprovider`
  Expected: fallan los 3 `bug` existentes y todos los nuevos (`Settings` ignora los campos nuevos → no hay fail-closed ni admins por lista; `_hash_password` da ImportError; el registro duplicado no lanza).

- [ ] **Step 3: Implementar.** Settings con los dos campos. En el adaptador: si `not is_configured and not local_mode_enabled` → `UnauthorizedException("Autenticación no configurada.")` en `authenticate`, `register` y `refresh_tokens`. Email normalizado `email.strip().lower()`. `_local_register` guarda `password_hash` y falla si ya existe. `_local_authenticate` exige usuario registrado y `_verify_password`; rol `admin` si el email normalizado está en `LOCAL_ADMIN_EMAILS` (split por coma, strip, lower) — calculado al autenticar, no al registrar. `refresh_token = secrets.token_urlsafe(32)`, guardado en `_local_refresh_tokens`. `_local_refresh(refresh_token)` busca el token; desconocido → `UnauthorizedException`; emite tokens para ese email (ignora el `email` del cliente). Quitar el marcador `bug` de los 3 tests.

- [ ] **Step 4: Flag en conftest raíz y compose.yml**; ajustar `test_auth_fastapi_endpoints` para registrar antes del login.

- [ ] **Step 5: Verde.** `uv run python -m pytest services/auth-service tests/integration -q -p no:cacheprovider`
  Expected: auth-service todo verde; `tests/integration` solo los 2 fallos ya conocidos del asunto "¡Compra exitosa!".

### Task 2: `/send-receipt` solo al email del token

**Files:**
- Modify: `services/notifications-service/src/notifications_service/presentation/router.py` (`send_receipt`)
- Test: `services/notifications-service/tests/api/test_notifications_api.py`, `.../api/test_receipt_escaping.py`

**Interfaces:** Consumes `TokenPayload.email: str | None` (nexus-security).

- [ ] **Step 1: Tests (RED)** en `test_notifications_api.py`:

```python
async def test_receipt_to_someone_else_is_forbidden(client, smtp_send):
    r = await client.post(f"{BASE}/send-receipt", json={**RECEIPT, "customer_email": "victim@x.cl"},
                          headers=auth_headers(email="ana@b.cl"))
    assert r.status_code == 403
    smtp_send.assert_not_awaited()

async def test_receipt_with_token_without_email_is_forbidden(client, smtp_send):
    r = await client.post(f"{BASE}/send-receipt", json=RECEIPT, headers=auth_headers(email=None))
    assert r.status_code == 403
    smtp_send.assert_not_awaited()

async def test_receipt_email_match_is_case_insensitive(client, smtp_send):
    r = await client.post(f"{BASE}/send-receipt", json={**RECEIPT, "customer_email": "ANA@B.CL"},
                          headers=auth_headers(email="ana@b.cl"))
    assert r.status_code == 200
    assert smtp_send.await_args.args[0]["To"] == "ana@b.cl"
```

  Y en los tests existentes de `/send-receipt` (ambos archivos) usar `auth_headers(email="ana@b.cl")`, que coincide con el `customer_email` del payload.

- [ ] **Step 2: Correr y ver fallar.** `uv run python -m pytest services/notifications-service/tests/api -q -p no:cacheprovider`
  Expected: los 2 de 403 fallan (hoy devuelven 200) y el de mayúsculas falla por `To` == "ANA@B.CL".

- [ ] **Step 3: Implementar.** En `send_receipt` usar `current_user`; el 400 por destinatario vacío se mantiene antes. Sin `current_user.email` → 403 "El token no incluye un correo."; distinto → 403 "Solo puedes enviarte la boleta a tu propio correo."; destinatario = email del token.

- [ ] **Step 4: Verde.** `uv run python -m pytest services/notifications-service -q -p no:cacheprovider`
  Expected: todo verde salvo los 4 `bug` de escape HTML.

### Task 3: Proxy de la boleta reenvía el token (nexus-frontend)

**Files:**
- Modify: `C:\nexus\nexus-frontend\src\app\api\v1\notifications\send-receipt\route.ts` (fetch al backend: `headers: buildForwardHeaders(request)`)
- Test: `C:\nexus\nexus-frontend\src\app\api\v1\notifications\send-receipt\__tests__\route.test.ts`

**Interfaces:** Consumes `buildForwardHeaders(request): Headers` de `@/infrastructure/bff/forwardHeaders`.

- [ ] **Step 1: Test (RED)** con `vi.stubGlobal('fetch', ...)` que devuelve `200 {success:true}`; `new NextRequest('http://localhost/api/v1/notifications/send-receipt', {method:'POST', headers:{authorization:'Bearer abc'}, body: JSON.stringify(<receipt válido>)})`. Asserts: `new Headers(fetch.mock.calls[0][1].headers).get('authorization') === 'Bearer abc'`. Segundo test: sin auth, backend mock 401 → respuesta del proxy con status 401.
- [ ] **Step 2:** `pnpm vitest run src/app/api/v1/notifications/send-receipt` → Expected: el primero FAIL (authorization null).
- [ ] **Step 3:** Importar y usar `buildForwardHeaders(request)`.
- [ ] **Step 4:** Mismo comando → Expected: PASS. Avisar a la sesión `nexus-frontend` del cambio.

### Cierre
- Suite completa backend: `uv run python -m pytest -q -p no:cacheprovider` → Expected: solo fallan los `bug` no críticos (10) + 2 de `test_purchase_flow_sdd.py`.
- Revisión final del diff por un revisor fresco (skill executing-plans).
