# Diseño: identidad Cognito y mensajería AWS para desplegar en el Learner Lab

Fecha: 2026-11-22 · Repos: nexus-backend, nexus-frontend, nexus-infrastructure

## Problema

1. **Suplantación de identidad.** El BFF (nexus-frontend) reenvía las cabeceras `x-user-id`, `x-user-email` y
   `x-user-role` que manda el navegador, y `nexus_security.get_current_user` las acepta sin validar. Un cliente
   puede actuar como cualquier usuario o como `admin`.
2. **Tokens de Cognito rechazados.** Fuera de esas cabeceras, el backend solo valida JWT HS256 con `JWT_SECRET`.
   Cognito emite RS256: en AWS ningún token real sería aceptado.
3. **RabbitMQ no existe en el Learner Lab** (ni Amazon MQ). Los eventos (`user.registered`, `order.*`,
   `catalog.*`) se perderían.
4. **Credenciales reales embebidas** como valores por defecto (Groq, Pinecone, Tavily, Gmail) en `config.py`;
   terminarían dentro de las imágenes de ECR.
5. Rutas sin autenticación ya documentadas por tests `bug`: stock del catálogo, `/notifications/email` (relay
   abierto), `/send-receipt`, `GET/pay` de órdenes (con IDOR) y `/assistant/chat`.

## Decisiones (aprobadas por el usuario)

- La identidad la valida **cada microservicio** (defensa en profundidad); API Gateway queda con WAF + throttling.
- Mensajería: **SNS + SQS** (fan-out equivalente al exchange topic de RabbitMQ). Ambos figuran en el lab.

## Diseño

### Identidad (`nexus-security`)
- Modo **Cognito** (si `COGNITO_USER_POOL_ID` y `COGNITO_APP_CLIENT_ID` están definidos): verifica RS256 contra el
  JWKS del User Pool (`PyJWKClient`, caché), `iss` = `https://cognito-idp.<region>.amazonaws.com/<pool>`,
  `exp`, y el cliente: `aud` (ID token) o `client_id` (access token). Rol: `admin` si `admins` está en
  `cognito:groups`; si no, `customer`. Email: claim `email` (ID token).
- Modo **local** (sin Cognito): HS256 con `JWT_SECRET`, como hoy (tests y desarrollo).
- **Se eliminan** las cabeceras `X-User-Id/Email/Role` como fuente de identidad.
- Carrito de invitado: dependencia `get_cart_owner` → `sub` del token, o `guest:<uuid>` desde `X-Guest-Id`
  (solo UUID válidos; nunca colisiona con un `sub` real).

### Autorización por ruta
| Ruta | Regla |
|---|---|
| `PATCH /catalog/products/{id}/stock` | admin |
| `POST /notifications/email` | admin |
| `POST /notifications/send-receipt` | autenticado |
| `GET /orders/{id}`, `POST /orders/{id}/pay` | autenticado y dueño de la orden (si no, 404) |
| `POST /assistant/chat` | autenticado |

### Mensajería (`nexus-events`)
- `EventPublisher(topic_arn)`: `sns.publish` con el JSON del evento y el atributo `event_type` (= routing key).
  Sin `topic_arn` → no-op con log (desarrollo local). Sin aio-pika.
- `SqsConsumer(queue_url, handler)`: long polling (20 s), entrega `(event_type, payload)` al handler y borra el
  mensaje solo si el handler no falla (reintentos → DLQ por redrive policy).
- Suscripciones SNS → SQS con *raw delivery* y *filter policy* por `event_type`:
  notifications = `order.*` + `user.registered`; catalog = `order.created`, `order.payment_failed`;
  analytics = todo (Lambda → DynamoDB `events` + data lake S3, reemplaza a Kinesis).
- El outbox de orders publica con `publisher.publish_raw(event_type, payload_json)`.

### Secretos
- Sin valores por defecto reales: `GROQ_API_KEY`, `PINECONE_API_KEY`, `TAVILY_API_KEY`, `SMTP_*`, `GMAIL_*` = `""`.
- El adaptador SMTP no envía si no hay credenciales (test `bug` existente).
- En AWS vienen de Secrets Manager → Kubernetes Secret (lo crea `deploy.sh`).

## Fuera de alcance (siguen como tests `bug`)
Escape HTML en correos, stock acumulado del carrito, idempotencia de órdenes, modo local de auth, historial
compartido del asistente sin `session_id`, fallo del vector store en el stream.
