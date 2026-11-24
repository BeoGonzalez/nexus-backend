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
# El clúster puede tardar en converger tras el rollout (un pod reprogramado, una probe que aún arranca):
# cada servicio se reintenta cada VERIFY_INTERVAL s hasta VERIFY_TIMEOUT s y solo se reporta el último intento.
#
# Requiere: kubectl con contexto del clúster, jq, curl. Variables: EKS_NAMESPACE, SERVICES, IMAGES_DIR
# (image-<svc>/image-ref.txt con repo@digest). Opcionales: MAX_RESTARTS (0), API_BASE_URL,
# VERIFY_TIMEOUT (240), VERIFY_INTERVAL (15). Sale con 1 si algún servicio no queda sano (el workflow hace rollback).
set -uo pipefail

: "${EKS_NAMESPACE:?}" "${SERVICES:?}" "${IMAGES_DIR:?}"
MAX_RESTARTS="${MAX_RESTARTS:-0}"
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-240}"
VERIFY_INTERVAL="${VERIFY_INTERVAL:-15}"
for bin in kubectl jq curl; do
  command -v "$bin" > /dev/null || { echo "::error::Falta '${bin}' en el PATH"; exit 1; }
done

# Ruta pública de cada servicio (el ai-agent se publica como /assistant).
route() { case "$1" in ai-agent) echo assistant ;; *) echo "$1" ;; esac; }

# check_service <svc>: llena ERRORS y PASSED (arrays) con el resultado de un intento.
check_service() {
  local svc="$1" ref digest path deploy_json spec_image selector live count before code
  ERRORS=(); PASSED=()
  ref=$(tr -d '[:space:]' < "${IMAGES_DIR}/image-${svc}/image-ref.txt")
  digest="${ref#*@}"
  path="/api/v1/$(route "$svc")/health"

  if ! deploy_json=$(kubectl -n "$EKS_NAMESPACE" get deployment "$svc" -o json 2>/dev/null); then
    ERRORS+=("${svc}: no existe el Deployment"); return
  fi

  # 1. Imagen declarada = imagen firmada
  spec_image=$(jq -r '.spec.template.spec.containers[] | select(.name == "app") | .image' <<<"$deploy_json" | tr -d '\r')
  if [ "$spec_image" = "$ref" ]; then
    PASSED+=("Deployment declara ${ref}")
  else
    ERRORS+=("${svc}: el Deployment declara '${spec_image}', se esperaba '${ref}'")
  fi

  # 2. Rollout completo
  if jq -e '(.status.observedGeneration // 0) >= .metadata.generation
            and (.status.updatedReplicas // 0) == .spec.replicas
            and (.status.availableReplicas // 0) == .spec.replicas
            and ((.status.unavailableReplicas // 0) == 0)' <<<"$deploy_json" > /dev/null; then
    PASSED+=("rollout completo ($(jq -r .spec.replicas <<<"$deploy_json" | tr -d '\r') réplicas disponibles)")
  else
    ERRORS+=("${svc}: rollout incompleto: $(jq -c '{deseadas: .spec.replicas, actualizadas: .status.updatedReplicas, disponibles: .status.availableReplicas}' <<<"$deploy_json" | tr -d '\r')")
  fi

  # 3. Pods vivos: Ready, digest exacto y reinicios acotados.
  # Separador "|" (no tabulador): `read` colapsa tabuladores consecutivos y un campo vacío desplazaría el resto.
  selector=$(jq -r '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")' <<<"$deploy_json" | tr -d '\r')
  live=$(kubectl -n "$EKS_NAMESPACE" get pods -l "$selector" -o json | jq '[.items[] | select(.metadata.deletionTimestamp == null)]')
  count=$(jq length <<<"$live" | tr -d '\r')
  before=${#ERRORS[@]}
  [ "${count:-0}" -gt 0 ] || ERRORS+=("${svc}: no hay pods en ejecución")
  while IFS='|' read -r name ready image_id restarts; do
    [ -n "$name" ] || continue
    if [ -z "$image_id" ]; then
      ERRORS+=("${svc}: el pod ${name} aún no tiene contenedor en ejecución"); continue
    fi
    [ "$ready" = "True" ] || ERRORS+=("${svc}: el pod ${name} no está Ready")
    [ "${image_id##*@}" = "$digest" ] || ERRORS+=("${svc}: el pod ${name} ejecuta ${image_id##*@}, se esperaba ${digest}")
    [ "${restarts:-0}" -le "$MAX_RESTARTS" ] || ERRORS+=("${svc}: el pod ${name} se reinició ${restarts} veces (máximo ${MAX_RESTARTS})")
  done < <(jq -r '.[] | [
      .metadata.name,
      ((.status.conditions // []) | map(select(.type == "Ready"))[0].status // "False"),
      ((.status.containerStatuses // []) | map(select(.name == "app"))[0].imageID // ""),
      ((.status.containerStatuses // []) | map(select(.name == "app"))[0].restartCount // 0 | tostring)
    ] | join("|")' <<<"$live" | tr -d '\r')
  [ "${#ERRORS[@]}" -eq "$before" ] && PASSED+=("${count} pod(s) Ready, con digest ${digest:0:19}… y reinicios ≤ ${MAX_RESTARTS}")

  # 4. Salud dentro del clúster
  if kubectl get --raw "/api/v1/namespaces/${EKS_NAMESPACE}/services/${svc}:80/proxy${path}" --request-timeout=15s > /dev/null 2>&1; then
    PASSED+=("GET ${path} (interno) = 200")
  else
    ERRORS+=("${svc}: GET ${path} dentro del clúster no respondió 200")
  fi

  # 5. Salud por la ruta pública
  if [ -n "${API_BASE_URL:-}" ]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${API_BASE_URL%/}/$(route "$svc")/health" || true)
    if [ "$code" = "200" ]; then
      PASSED+=("GET ${path} (API Gateway) = 200")
    else
      ERRORS+=("${svc}: GET ${path} por API Gateway devolvió ${code}")
    fi
  fi
}

failed_services=0
deadline=$(( $(date +%s) + VERIFY_TIMEOUT ))
for svc in $SERVICES; do
  attempt=1
  while :; do
    check_service "$svc"
    [ "${#ERRORS[@]}" -eq 0 ] && break
    [ "$(date +%s)" -ge "$deadline" ] && break
    echo "${svc}: intento ${attempt} con ${#ERRORS[@]} comprobación(es) pendiente(s) (${ERRORS[0]}); reintento en ${VERIFY_INTERVAL} s"
    attempt=$((attempt + 1))
    sleep "$VERIFY_INTERVAL"
  done
  if [ "${#ERRORS[@]}" -eq 0 ]; then
    echo "✓ ${svc}"
    for p in "${PASSED[@]}"; do echo "    ✓ ${p}"; done
  else
    failed_services=$((failed_services + 1))
    echo "✗ ${svc}"
    for p in "${PASSED[@]}"; do echo "    ✓ ${p}"; done
    for e in "${ERRORS[@]}"; do echo "::error::${e}"; done
  fi
done

if [ "$failed_services" -gt 0 ]; then
  echo "::error::Verificación del despliegue: ${failed_services} servicio(s) no quedaron sanos tras ${VERIFY_TIMEOUT} s"
  exit 1
fi
echo "Verificación del despliegue: OK (${SERVICES})"
