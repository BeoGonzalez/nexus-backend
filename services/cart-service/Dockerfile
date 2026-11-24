# syntax=docker/dockerfile:1.7
# cart-service: imagen multi-stage con uv (OWASP A02/A03/A08).
# Build desde la raíz del monorepo:  docker build -f services/cart-service/Dockerfile .
# - Bases fijadas por digest (actualízalas con Dependabot/Renovate).
# - Runtime sin uv, sin pip ni compiladores: solo el virtualenv con el servicio y sus dependencias.
# - UID/GID 10001 sin shell; compatible con readOnlyRootFilesystem (único directorio escribible: /tmp).

FROM ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv

# ------------------------------------------------------------------------------ builder
# Misma base (por digest) en builder y runtime: el virtualenv apunta a /usr/local/bin/python3.11.
FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39 AS builder
COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE_TIMEOUT=600

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services/cart-service ./services/cart-service

# --frozen: el contexto solo trae este servicio, así que uv no puede revalidar el lock de todo el workspace;
# la coherencia lock <-> pyproject la exige el job "supply-chain" del pipeline (uv lock --check).
# --no-editable: los paquetes del workspace se instalan en site-packages; el runtime no necesita el código fuente.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package cart-service

# ------------------------------------------------------------------------------ runtime
FROM python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39 AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/tmp \
    TMPDIR=/tmp

# Parches de seguridad del SO; fuera pip/setuptools/wheel del Python base (no se usan en runtime).
# hadolint ignore=DL3005
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip setuptools wheel \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin app

WORKDIR /app
# Propiedad de root: el usuario de la app solo puede leer el código y las dependencias.
COPY --from=builder /app/.venv /app/.venv

USER 10001:10001
EXPOSE 8000

# Para docker compose; en EKS mandan las probes de Kubernetes.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/cart/health', timeout=4)"]

CMD ["python", "-m", "uvicorn", "cart_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--timeout-graceful-shutdown", "30"]
