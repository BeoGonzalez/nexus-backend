"""Pruebas de carga y abuso de Nexus con Locust (rendimiento + DAST de comportamiento bajo carga).

Uso (stack local de docker compose):
    uvx locust -f tests/performance/locustfile.py --headless -u 50 -r 10 -t 2m \
        --csv perf/nexus --html perf/nexus.html

Variables:
    NEXUS_BASE        host base de los servicios (por defecto http://localhost)
    LOCUST_JWT_SECRET secreto HS256 del modo local de compose (NUNCA el de producción)
    LOCUST_ENABLE_LLM=true  incluye usuarios del asistente IA (consume cuota real de Groq)

Clases:
    Shopper   navega el catálogo y usa el carrito como invitado (tráfico principal)
    Buyer     autenticado: crea órdenes, las paga y lista sus pedidos
    Attacker  fuerza bruta de login y tokens forjados: el éxito es recibir 429/401, nunca 200/500
    AssistantUser (opcional) conversa con el asistente IA y verifica las cuotas LLM06
"""

from __future__ import annotations

import os
import random
import time
import uuid

import jwt
from locust import HttpUser, between, events, task

BASE = os.getenv("NEXUS_BASE", "http://localhost").rstrip("/")
PORTS = {"auth": 8001, "catalog": 8002, "cart": 8003, "orders": 8004, "recommendations": 8006, "assistant": 8007}
SECRET = os.getenv("LOCUST_JWT_SECRET", "super-secret-jwt-key-for-local-development")
PRODUCT_IDS: list[str] = []


def url(service: str, path: str) -> str:
    return f"{BASE}:{PORTS[service]}/api/v1/{service}{path}"


def token(sub: str, role: str = "customer") -> str:
    claims = {"sub": sub, "role": role, "email": f"{sub}@load.test", "email_verified": True,
              "exp": int(time.time()) + 3600}
    return jwt.encode(claims, SECRET, algorithm="HS256")


@events.test_start.add_listener
def load_catalog(environment, **_kw):
    import httpx

    try:
        r = httpx.get(url("catalog", "/products?limit=100"), timeout=10)
        PRODUCT_IDS.extend(p["id"] for p in r.json() if p.get("stock", 0) > 0)
    except Exception as exc:  # el catálogo puede estar vacío en un entorno nuevo
        print(f"[locust] no se pudo cargar el catálogo: {exc}")
    print(f"[locust] {len(PRODUCT_IDS)} productos con stock disponibles para la prueba")


class Shopper(HttpUser):
    weight = 6
    wait_time = between(1, 3)
    host = BASE

    def on_start(self):
        self.guest = str(uuid.uuid4())

    @task(5)
    def browse_catalog(self):
        self.client.get(url("catalog", "/products?limit=50"), name="GET /catalog/products")

    @task(3)
    def product_detail(self):
        if PRODUCT_IDS:
            self.client.get(url("catalog", f"/products/{random.choice(PRODUCT_IDS)}"), name="GET /catalog/products/{id}")

    @task(2)
    def trending(self):
        self.client.get(url("recommendations", "/trending"), name="GET /recommendations/trending")

    @task(2)
    def guest_cart(self):
        headers = {"X-Guest-Id": self.guest}
        if PRODUCT_IDS:
            self.client.post(url("cart", "/items"), json={"product_id": random.choice(PRODUCT_IDS), "quantity": 1},
                             headers=headers, name="POST /cart/items (invitado)")
        self.client.get(url("cart", ""), headers=headers, name="GET /cart (invitado)")


class Buyer(HttpUser):
    weight = 3
    wait_time = between(2, 5)
    host = BASE

    def on_start(self):
        self.headers = {"Authorization": f"Bearer {token(f'buyer-{uuid.uuid4().hex[:8]}')}"}

    @task(3)
    def my_orders(self):
        self.client.get(url("orders", ""), headers=self.headers, name="GET /orders")

    @task(1)
    def purchase(self):
        if not PRODUCT_IDS:
            return
        body = {"items": [{"product_id": random.choice(PRODUCT_IDS), "quantity": 1}],
                "idempotency_key": uuid.uuid4().hex}
        with self.client.post(url("orders", ""), json=body, headers=self.headers, name="POST /orders",
                              catch_response=True) as r:
            if r.status_code == 409:  # sin stock: comportamiento correcto bajo carga
                r.success()
                return
            if r.status_code != 201:
                r.failure(f"status {r.status_code}")
                return
            order_id = r.json()["id"]
        self.client.post(url("orders", f"/{order_id}/pay"), headers=self.headers, name="POST /orders/{id}/pay")
        # Un segundo pago debe ser rechazado (409): verificación de la máquina de estados bajo concurrencia.
        with self.client.post(url("orders", f"/{order_id}/pay"), headers=self.headers,
                              name="POST /orders/{id}/pay (doble pago)", catch_response=True) as again:
            if again.status_code == 409:
                again.success()
            else:
                again.failure(f"doble pago aceptado: {again.status_code}")


class Attacker(HttpUser):
    """El éxito de esta clase es que el sistema SE DEFIENDA: 401/403/422/429 son correctos; 200 o 5xx, fallos."""

    weight = 1
    wait_time = between(0.1, 0.5)
    host = BASE

    def _expect_blocked(self, r, allowed=(401, 403, 404, 409, 422, 429)):
        if r.status_code in allowed:
            r.success()
        else:
            r.failure(f"ataque no bloqueado: {r.status_code}")

    @task(3)
    def brute_force_login(self):
        body = {"email": "victima@nexus.cl", "password": f"intento-{random.randint(0, 10**6)}"}
        with self.client.post(url("auth", "/login"), json=body, name="ATAQUE login fuerza bruta",
                              catch_response=True) as r:
            self._expect_blocked(r)

    @task(2)
    def forged_admin_token(self):
        forged = jwt.encode({"sub": "x", "role": "admin", "exp": int(time.time()) + 60}, "adivinado", algorithm="HS256")
        with self.client.post(url("catalog", "/products"), headers={"Authorization": f"Bearer {forged}"},
                              json={"title": "Gratis", "description": "x", "price_clp": 1, "stock": 1},
                              name="ATAQUE token admin forjado", catch_response=True) as r:
            self._expect_blocked(r, (401,))

    @task(2)
    def idor_other_order(self):
        with self.client.get(url("orders", f"/{uuid.uuid4()}"), headers={"Authorization": f"Bearer {token('mallory')}"},
                             name="ATAQUE IDOR orden ajena", catch_response=True) as r:
            self._expect_blocked(r, (403, 404))

    @task(1)
    def body_bomb(self):
        with self.client.post(url("orders", ""), headers={"Authorization": f"Bearer {token('mallory')}"},
                              json={"items": [], "padding": "A" * 2_000_000}, name="ATAQUE cuerpo 2 MB",
                              catch_response=True) as r:
            self._expect_blocked(r, (413,))


if os.getenv("LOCUST_ENABLE_LLM", "").lower() == "true":

    class AssistantUser(HttpUser):
        weight = 1
        wait_time = between(5, 10)
        host = BASE

        def on_start(self):
            self.headers = {"Authorization": f"Bearer {token(f'chat-{uuid.uuid4().hex[:8]}')}"}

        @task
        def chat(self):
            body = {"query": "Recomiéndame un roguelike barato", "session_id": "load-test"}
            with self.client.post(url("assistant", "/chat"), json=body, headers=self.headers, name="POST /assistant/chat",
                                  catch_response=True, stream=True) as r:
                if r.status_code in (200, 429):  # 429 = cuota LLM06 funcionando
                    r.success()
                else:
                    r.failure(f"status {r.status_code}")
