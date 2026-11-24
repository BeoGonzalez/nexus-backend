#!/usr/bin/env bash
# Verificación posterior al despliegue en EKS (OWASP A08: lo que corre es exactamente lo que se firmó).
#
# Por cada servicio comprueba, contra el clúster real:
#   1. El Deployment apunta a la imagen firmada por digest (repo@sha256:...) que verificó el pipeline.
#   2. El rollout está completo: generación observada, réplicas actualizadas == disponibles == deseadas.
#   3. Cada pod vivo del servicio está Ready, ejecuta ESE digest (status.containerStatuses[].imageID)
#      y no supera MAX_RESTARTS reinicios.
#   4. /health responde 200 dentro del clúster (proxy del API server -> Service -> pod).
#   5. Opcional: /health responde 200 por la ruta pública (API Gateway -> VPC Link -> NLB -> NodePort)
#      si API_BASE_URL está definida (p. ej. https://xxxx.execute-api.us-east-1.amazonaws.com/v1/api/v1).
#
# Requiere: kubectl con contexto del clúster, jq, curl. Variables: EKS_NAMESPACE, SERVICES, IMAGES_DIR
# (image-<svc>/image-ref.txt con repo@digest). Opcionales: MAX_RESTARTS (0), API_BASE_URL.
# Sale con 1 si cualquier comprobación falla (el workflow hace rollback).
set -uo pipefail

: "${EKS_NAMESPACE:?}" "${SERVICES:?}" "${IMAGES_DIR:?}"
MAX_RESTARTS="${MAX_RESTARTS:-0}"
failures=0
for bin in kubectl jq curl; do
  command -v "$bin" > /dev/null || { echo "::error::Falta '${bin}' en el PATH"; exit 1; }
done

fail() { echo "::error::$*"; failures=$((failures + 1)); }
ok() { echo "  ✓ $*"; }

# Ruta pública de cada servicio (el ai-agent se publica como /assistant).
route() { case "$1" in ai-agent) echo assistant ;; *) echo "$1" ;; esac; }

for svc in $SERVICES; do
  echo "::group::${svc}"
  ref=$(tr -d '[:space:]' < "${IMAGES_DIR}/image-${svc}/image-ref.txt")
  digest="${ref#*@}"
  path="/api/v1/$(route "$svc")/health"

  deploy_json=$(kubectl -n "$EKS_NAMESPACE" get deployment "$svc" -o json) || { fail "${svc}: no existe el Deployment"; echo "::endgroup::"; continue; }

  # 1. Imagen declarada = imagen firmada
  spec_image=$(jq -r '.spec.template.spec.containers[] | select(.name == "app") | .image' <<<"$deploy_json")
  if [ "$spec_image" = "$ref" ]; then
    ok "Deployment declara ${ref}"
  else
    fail "${svc}: el Deployment declara '${spec_image}', se esperaba '${ref}'"
  fi

  # 2. Rollout completo
  if jq -e '(.status.observedGeneration // 0) >= .metadata.generation
            and (.status.updatedReplicas // 0) == .spec.replicas
            and (.status.availableReplicas // 0) == .spec.replicas
            and ((.status.unavailableReplicas // 0) == 0)' <<<"$deploy_json" > /dev/null; then
    ok "rollout completo ($(jq -r .spec.replicas <<<"$deploy_json") réplicas disponibles)"
  else
    fail "${svc}: rollout incompleto: $(jq -c '{deseadas: .spec.replicas, actualizadas: .status.updatedReplicas, disponibles: .status.availableReplicas}' <<<"$deploy_json")"
  fi

  # 3. Pods vivos: Ready, digest exacto y reinicios acotados
  selector=$(jq -r '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")' <<<"$deploy_json")
  pods_json=$(kubectl -n "$EKS_NAMESPACE" get pods -l "$selector" -o json)
  live=$(jq '[.items[] | select(.metadata.deletionTimestamp == null)]' <<<"$pods_json")
  count=$(jq length <<<"$live")
  before=$failures
  [ "${count:-0}" -gt 0 ] || fail "${svc}: no hay pods en ejecución"
  while IFS=$'\t' read -r name ready image_id restarts; do
    [ -n "$name" ] || continue
    [ "$ready" = "True" ] || fail "${svc}: el pod ${name} no está Ready"
    [ "${image_id##*@}" = "$digest" ] || fail "${svc}: el pod ${name} ejecuta ${image_id##*@}, se esperaba ${digest}"
    [ "$restarts" -le "$MAX_RESTARTS" ] || fail "${svc}: el pod ${name} se reinició ${restarts} veces (máximo ${MAX_RESTARTS})"
  done < <(jq -r '.[] | [
      .metadata.name,
      ((.status.conditions // []) | map(select(.type == "Ready"))[0].status // "False"),
      ((.status.containerStatuses // []) | map(select(.name == "app"))[0].imageID // ""),
      ((.status.containerStatuses // []) | map(select(.name == "app"))[0].restartCount // 0)
    ] | @tsv' <<<"$live" | tr -d '\r')
  if [ "$failures" -eq "$before" ]; then
    ok "${count} pod(s) Ready, con digest ${digest:0:19}… y reinicios ≤ ${MAX_RESTARTS}"
  fi

  # 4. Salud dentro del clúster
  if kubectl get --raw "/api/v1/namespaces/${EKS_NAMESPACE}/services/${svc}:80/proxy${path}" --request-timeout=15s > /dev/null 2>&1; then
    ok "GET ${path} (interno) = 200"
  else
    fail "${svc}: GET ${path} dentro del clúster no respondió 200"
  fi

  # 5. Salud por la ruta pública
  if [ -n "${API_BASE_URL:-}" ]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 --retry 3 --retry-all-errors "${API_BASE_URL%/}/$(route "$svc")/health" || true)
    if [ "$code" = "200" ]; then
      ok "GET ${path} (API Gateway) = 200"
    else
      fail "${svc}: GET ${path} por API Gateway devolvió ${code}"
    fi
  fi
  echo "::endgroup::"
done

if [ "$failures" -gt 0 ]; then
  echo "::error::Verificación del despliegue: ${failures} comprobación(es) fallida(s)"
  exit 1
fi
echo "Verificación del despliegue: OK (${SERVICES})"
