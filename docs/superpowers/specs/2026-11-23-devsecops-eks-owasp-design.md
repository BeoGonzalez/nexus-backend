# Diseño: pipeline DevSecOps a ECR/EKS y hardening OWASP Top 10:2025 (Learner Lab)

Fecha: 2026-11-23 · Repo: nexus-backend (lectura de nexus-infrastructure)

## Intención

Que ningún cambio llegue a ECR/EKS sin pasar gates de seguridad mapeados a OWASP Top 10:2025, que las imágenes y
manifiestos estén endurecidos, y que los eventos de seguridad y errores lleguen a Grafana sin filtrar detalles al
cliente. El destino es el **AWS Academy Learner Lab actual** (confirmado por el usuario).

## Restricciones del Learner Lab (de `nexus-infrastructure/docs/LEARNER-LAB.md`)

- **No se pueden crear roles IAM ni OIDC providers** → GitHub no puede asumir un rol por OIDC. El pipeline usa las
  credenciales temporales del lab (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` en GitHub
  Secrets, se renuevan cada sesión) a través de `aws-actions/configure-aws-credentials`. `id-token: write` se
  mantiene para **Sigstore** (Cosign keyless y attestations usan el OIDC de GitHub, no IAM).
- **Sin AWS Load Balancer Controller** (necesita IRSA/rol propio). La entrada sigue siendo API Gateway (TLS) → VPC
  Link → NLB interno → NodePort. **No se crea `ingress.yaml`**: TLS lo termina API Gateway y el ALB de Terraform
  (frontend) ya fuerza HTTPS.
- ECR con tags **IMMUTABLE**; `LabRole` solo lee, el usuario del lab escribe.
- X-Ray denegado; el stack Grafana (Collector/Prometheus/Loki/Tempo) no está desplegado aún: la app exporta por OTLP
  solo si `OTEL_EXPORTER_OTLP_ENDPOINT` está definido (si no, no-op).

## Enfoques considerados

1. **Pipeline solo `kubectl set image`, manifiestos en infra** (como `docs/examples/deploy-backend.yml`). Simple,
   pero los manifiestos no se auditan en este repo y `k8s/` no existiría aquí.
2. **`k8s/` del backend como fuente de verdad de las cargas** (Deployment/Service/HPA/PDB/NetworkPolicy por
   servicio, con kustomize), auditado con Checkov/kube-score y aplicado por el pipeline con la imagen fijada por
   digest. Infra conserva Namespace, ServiceAccount, Secrets (desde Secrets Manager) y jobs de BD. **Elegido.**
3. Helm chart. Descartado: añade una herramienta más sin ganancia frente a kustomize (ya lo usa infra).

## Diseño

### Pipeline `.github/workflows/devsecops-eks.yml`
- Disparadores: `pull_request` (gates + build sin push) y `push` a `main` (gates + push + firma + despliegue).
- Acciones fijadas por **SHA completo** con comentario de versión.
- Jobs (todos bloqueantes antes de `publish`/`deploy`):
  - `secrets` (A04): Gitleaks sobre todo el historial + check de que ningún `kind: Secret` con `data`/`stringData`
    está en `k8s/`.
  - `sast` (A05): Bandit (`-lll`… severidad media+) y Semgrep (`p/python`, `p/owasp-top-ten`, `p/kubernetes`,
    `p/dockerfile`; las reglas FastAPI viven en `p/python`).
  - `supply-chain` (A03): `uv lock --check`, `uv sync --locked`, `pip-audit` sobre `uv export` con hashes, SBOM
    CycloneDX del entorno.
  - `tests` (A01/A07/A10/A06/A09): `pytest -m "not bug"` con Postgres real (Testcontainers en el runner). Los tests
    `bug` (bugs conocidos) corren en un job aparte, informativo.
  - `iac` (A02): Hadolint en los 7 Dockerfiles, Checkov y kube-score sobre `kustomize build k8s/`.
  - `build` (matriz de 7 servicios, A02/A08): build multi-stage → Trivy (HIGH,CRITICAL, `ignore-unfixed`) →
    en `main`: push a ECR con tag `${{ github.sha }}`, Cosign sign keyless por digest, SBOM CycloneDX de la imagen
    attestada con Cosign, `actions/attest-build-provenance` con `push-to-registry`.
  - `deploy` (solo `main`, environment `lab`): `kustomize edit set image` con `repo@digest` de cada servicio,
    ConfigMap no sensible desde `vars`, `kubectl apply -k k8s/`, `kubectl rollout status` por servicio.
- Variables: `vars.AWS_ACCOUNT_ID`, `vars.AWS_REGION`, `vars.ECR_REPOSITORY` (prefijo, p. ej. `nexus` →
  `nexus-<servicio>`), `vars.EKS_CLUSTER_NAME`, `vars.EKS_NAMESPACE`, más `vars.COGNITO_USER_POOL_ID`,
  `vars.COGNITO_APP_CLIENT_ID`, `vars.EVENTS_TOPIC_ARN`, `vars.OTEL_EXPORTER_OTLP_ENDPOINT`, `vars.CORS_ALLOWED_ORIGINS`.

### Contenedor (A02/A08)
- Los 7 Dockerfiles: builder `ghcr.io/astral-sh/uv` fijado, `uv sync --locked --no-dev --no-editable`; runtime
  `python:3.11-slim-bookworm` (se respeta `.python-version` 3.11, no 3.12) fijado por digest, usuario `10001`, sin
  shell de build tools, `/tmp` como único directorio escribible, `HOME=/tmp`, sin `HEALTHCHECK` de Docker (las
  probes las hace Kubernetes) → se mantiene para compose con `python -c`. Sin `curl`.

### Kubernetes `k8s/` (A01/A02)
- `kustomization.yaml`, `<servicio>.yaml` (Deployment + Service NodePort + HPA + PDB) ×7, `networkpolicy.yaml`,
  `templates/secret.example.yaml` (fuera del árbol que aplica kustomize, para que un `apply` nunca pise los
  Secrets reales).
- Mismos nombres, puertos y NodePorts que `nexus-infrastructure` (30081–30087) para no romper el NLB.
- Variables sensibles con `valueFrom.secretKeyRef` sobre `<servicio>-env` (las claves que ya crea `deploy.sh`).
- NetworkPolicy: default-deny + la regla `backend` de infra (idéntica) + egress al OTel Collector
  (`namespace observability`, 4317/4318).
- Seguimiento en infra (fuera de este repo): `deploy.sh` debe dejar de renderizar las cargas y solo crear Secrets,
  ConfigMap y jobs; si no, el último en aplicar gana.

### Aplicación (nexus-core / nexus-security)
- `nexus_core.infrastructure.logging`: JSON con `trace_id`/`span_id`, filtro de redacción (Authorization, tokens,
  contraseñas, secretos, emails enmascarados) y `log_security_event()`.
- `nexus_core.infrastructure.telemetry.setup_telemetry(app, service)`: OpenTelemetry (trazas + métricas OTLP) solo
  si hay endpoint; FastAPIInstrumentor.
- `nexus_core.presentation.errors.install_exception_handlers(app)` (A10): dominio → 404/409/401/403; validación →
  422 sin eco del input; `HTTPException` intacta; cualquier otra → 500 genérico con `request_id`; traza completa
  solo al log.
- `nexus_core.presentation.security.install_security_middleware(app, …)` (A06): CORS por allowlist
  (`CORS_ALLOWED_ORIGINS`, sin `*` con credenciales), TrustedHost opcional (`ALLOWED_HOSTS`, health exento),
  cabeceras HSTS/CSP/nosniff/frame/referrer, `X-Request-ID`, log de seguridad para 401/403/429.
- `nexus_security.rate_limit`: limitador en memoria por ventana deslizante (por pod; API Gateway throttling es la
  capa global) aplicado a `/auth/login`, `/register`, `/forgot-password`, `/reset-password`, `/confirm`,
  `/resend-code`.
- `verify_token` fail-closed: sin Cognito y sin `JWT_SECRET` explícito → 401 (hoy cae a un secreto conocido).
- Docs OpenAPI desactivadas salvo `ENABLE_API_DOCS=true`.

### Grafana (A09)
- `observability/grafana-eks-security-alerts.yaml`: reglas (formato Prometheus rules, importable en Grafana
  Alerting/Mimir) para picos 401/403, 429, 5xx, reinicios de pods y pods en CrashLoopBackOff.

## No-objetivos
- Desplegar el stack Grafana/OTel Collector en el clúster.
- Arreglar los tests marcados `bug` (se reportan, no bloquean).
- Cambiar `nexus-infrastructure`.

## Decisiones del implementador (marcadas como propias)
- Python 3.11 en vez de 3.12 (coherente con `.python-version` y el lock).
- Sin `ingress.yaml` (sin AWS LBC en el lab).
- `secret.example.yaml` en `k8s/templates/`.
