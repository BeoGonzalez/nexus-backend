# Diseño corto: bugs críticos restantes (auth local + /send-receipt)

Fecha: 2026-11-22 · Repos: nexus-backend (+1 línea en nexus-frontend)

## Contexto

La spec `2026-11-22-aws-identity-and-messaging-design.md` (otra sesión, ya implementada) cerró: stock del
catálogo (admin), `/notifications/email` (admin), GET/pay de órdenes (dueño o 404), `/assistant/chat`
(autenticado), cabeceras X-User-* y secretos embebidos. Suite actual: 305 passed, 15 failed (13 `bug` + 2 de
`test_purchase_flow_sdd.py`). Quedan dos huecos críticos de seguridad:

1. **Auth en modo local es fail-open** (3 tests `bug` en `test_cognito_adapter.py`): acepta cualquier
   contraseña, da `admin` si el email contiene "admin" y `refresh` emite tokens para cualquier email.
   Si en EKS faltan las variables de Cognito, cualquiera entra como cualquiera.
2. **`/send-receipt` es un relay para cualquier usuario autenticado**: exige token, pero envía a
   `customer_email` del body con HTML del cliente → cualquiera con cuenta manda correos de phishing desde la
   cuenta de la tienda. Además el proxy del frontend no reenvía el token, así que hoy la boleta da 401.

## Enfoques (elegido: A)

- **A — Destinatario = email del token.** Mínimo cambio; lo peor posible es enviarse correos a sí mismo.
  Requiere que el proxy de Next.js reenvíe el token (1 línea).
- B — `/send-receipt` solo admin y quitar la llamada del frontend (queda la boleta por evento). Descartado por
  el usuario: se pierde la boleta con claves.

## Decisiones

### Auth local (`auth_service/infrastructure/cognito.py`, `config.py`)
- Modo local solo si `AUTH_LOCAL_MODE=true`. Sin Cognito y sin el flag → `UnauthorizedException`
  ("autenticación no configurada"); nunca emite tokens (fail-closed). `compose.yml` lo activa en
  auth-service; el `conftest.py` raíz también (entorno de tests).
- Contraseñas: hash `hashlib.scrypt` con salt aleatorio (stdlib, sin dependencias nuevas), comparación con
  `hmac.compare_digest`. Usuario no registrado o contraseña incorrecta → `UnauthorizedException`.
- Rol admin solo si el email está en `LOCAL_ADMIN_EMAILS` (lista separada por comas, vacía por defecto).
- Refresh: el login local emite un refresh token opaco (`secrets.token_urlsafe`) guardado en memoria →
  email. `refresh` solo acepta tokens emitidos; desconocido → `UnauthorizedException`.
- Sigue en memoria por proceso (es modo desarrollo); no se persiste.

### `/send-receipt` (`notifications_service/presentation/router.py`)
- El destinatario es `current_user.email`. Si el token no trae email → 403. Si `customer_email` del body
  difiere (sin distinguir mayúsculas) → 403. Sin excepción para admin (YAGNI).
- Los tests `test_receipt_escaping.py` pasan a usar el email del token como `customer_email`.

### Frontend (`nexus-frontend/src/app/api/v1/notifications/send-receipt/route.ts`)
- Usar `buildForwardHeaders(request)` (ya existe y reenvía `authorization`/cookie `token`) en vez de solo
  `Content-Type`. La sesión guarda el ID token de Cognito, que trae `email`.

## No-objetivos (siguen como tests `bug`, no son críticos de seguridad)
Escape HTML en correos, stock acumulado del carrito, idempotencia y doble pago de órdenes, historial compartido
del asistente sin `session_id`, fallo del vector store. `test_purchase_flow_sdd.py` sigue pendiente de tu decisión.

## Verificación
TDD: los 3 tests `bug` de auth local son el RED (se les quita el marcador al pasar) + tests nuevos para el flag
fail-closed, admin por lista, refresh válido y el destinatario de `/send-receipt`. Suite completa en verde salvo
los `bug` restantes listados arriba.
