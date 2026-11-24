#!/usr/bin/env bash
# Autoriza temporalmente la IP pública del runner en el endpoint público del API de EKS (OWASP A01/A02).
#
#   eks-public-access.sh open    -> añade <ip-del-runner>/32 a publicAccessCidrs y espera a que se aplique
#   eks-public-access.sh close   -> quita esa IP (conserva las demás, p. ej. la /32 del administrador)
#
# El clúster sigue restringido a IPs concretas (terraform: eks_public_access_cidrs); los runners de GitHub
# no tienen IP fija, así que se abre solo la del runner y solo mientras dura el despliegue.
# Requiere: AWS_REGION, EKS_CLUSTER_NAME, credenciales AWS, jq. En "close" usa RUNNER_CIDR si está definida.
set -euo pipefail

action="${1:?uso: $0 open|close}"
: "${AWS_REGION:?}" "${EKS_CLUSTER_NAME:?}"

current_cidrs() {
  aws eks describe-cluster --region "$AWS_REGION" --name "$EKS_CLUSTER_NAME" \
    --query 'cluster.resourcesVpcConfig.publicAccessCidrs' --output json
}

# Aplica la lista de CIDRs y espera a que la actualización termine (EKS tarda ~2-5 min).
apply_cidrs() {
  local cidrs_json="$1" csv update_id status attempt
  csv=$(jq -r 'join(",")' <<<"$cidrs_json")
  for attempt in $(seq 1 20); do # otra actualización en curso -> ResourceInUseException: reintentar
    if update_id=$(aws eks update-cluster-config --region "$AWS_REGION" --name "$EKS_CLUSTER_NAME" \
      --resources-vpc-config "endpointPublicAccess=true,endpointPrivateAccess=true,publicAccessCidrs=${csv}" \
      --query 'update.id' --output text 2>/tmp/eks-update.err); then
      break
    fi
    if ! grep -q ResourceInUseException /tmp/eks-update.err; then cat /tmp/eks-update.err >&2; return 1; fi
    echo "Otra actualización del clúster en curso; reintento ${attempt}/20 en 30 s"
    sleep 30
  done
  [ -n "${update_id:-}" ] || { echo "::error::No se pudo actualizar publicAccessCidrs"; return 1; }
  for attempt in $(seq 1 60); do
    status=$(aws eks describe-update --region "$AWS_REGION" --name "$EKS_CLUSTER_NAME" \
      --update-id "$update_id" --query 'update.status' --output text)
    case "$status" in
      Successful) echo "publicAccessCidrs actualizado: ${csv}"; return 0 ;;
      Failed|Cancelled) echo "::error::La actualización ${update_id} terminó en ${status}"; return 1 ;;
    esac
    sleep 15
  done
  echo "::error::Tiempo de espera agotado para la actualización ${update_id}"
  return 1
}

case "$action" in
  open)
    ip=$(curl -fsS --retry 3 https://checkip.amazonaws.com | tr -d '[:space:]')
    [[ "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "::error::IP pública inválida: '${ip}'"; exit 1; }
    cidr="${ip}/32"
    echo "RUNNER_CIDR=${cidr}" >> "${GITHUB_ENV:-/dev/null}"
    cidrs=$(current_cidrs)
    if jq -e --arg c "$cidr" 'index($c) != null or index("0.0.0.0/0") != null' <<<"$cidrs" > /dev/null; then
      echo "El endpoint ya acepta ${cidr}; no se modifica."
      echo "RUNNER_CIDR_ADDED=false" >> "${GITHUB_ENV:-/dev/null}"
      exit 0
    fi
    echo "RUNNER_CIDR_ADDED=true" >> "${GITHUB_ENV:-/dev/null}"
    apply_cidrs "$(jq -c --arg c "$cidr" '. + [$c]' <<<"$cidrs")"
    ;;
  close)
    : "${RUNNER_CIDR:?RUNNER_CIDR no definida: nada que cerrar}"
    cidrs=$(current_cidrs)
    remaining=$(jq -c --arg c "$RUNNER_CIDR" 'map(select(. != $c))' <<<"$cidrs")
    if [ "$remaining" = "$(jq -c . <<<"$cidrs")" ]; then
      echo "${RUNNER_CIDR} ya no estaba autorizada."
      exit 0
    fi
    # Nunca dejar la lista vacía: EKS la interpretaría como 0.0.0.0/0.
    [ "$(jq length <<<"$remaining")" -gt 0 ] || { echo "::error::Quitar ${RUNNER_CIDR} dejaría la lista vacía (= 0.0.0.0/0)"; exit 1; }
    apply_cidrs "$remaining"
    ;;
  *)
    echo "uso: $0 open|close" >&2
    exit 2
    ;;
esac
