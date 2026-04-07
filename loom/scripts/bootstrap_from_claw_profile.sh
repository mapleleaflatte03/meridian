#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/bootstrap_from_claw_profile.sh --profile <openclaw|openfang|zeroclaw> [options]

Options:
  --profile <name>        Required profile name.
  --root <path>           Loom runtime root.
  --kernel-path <path>    Meridian Kernel path (default: /opt/meridian-kernel).
  --org-id <id>           Institution/org id (default: local_foundry).
  --charter <text>        Charter text for init-nation.
  --agent-name <name>     Seed agent display name.
  --webhook-url <url>     Webhook URL for quickstart lane.
  --loom-bin <path>       Loom binary path (default: loom on PATH).
  -h, --help              Show help.

This script is additive. It bootstraps a Loom runtime and scaffolds an
adapter set that mirrors common Claw-family entry surfaces.
EOF
}

PROFILE=""
ROOT="${HOME}/.local/share/meridian-loom/runtime/default"
KERNEL_PATH="/opt/meridian-kernel"
ORG_ID="${MERIDIAN_ORG_ID:-local_foundry}"
CHARTER="Claw Migration Charter"
AGENT_NAME="Migration Assistant"
WEBHOOK_URL="https://example.com/loom-hook"
LOOM_BIN="${LOOM_BIN:-loom}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="${2:-}"
      shift 2
      ;;
    --root)
      ROOT="${2:-}"
      shift 2
      ;;
    --kernel-path)
      KERNEL_PATH="${2:-}"
      shift 2
      ;;
    --org-id)
      ORG_ID="${2:-}"
      shift 2
      ;;
    --charter)
      CHARTER="${2:-}"
      shift 2
      ;;
    --agent-name)
      AGENT_NAME="${2:-}"
      shift 2
      ;;
    --webhook-url)
      WEBHOOK_URL="${2:-}"
      shift 2
      ;;
    --loom-bin)
      LOOM_BIN="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${PROFILE}" ]]; then
  echo "--profile is required" >&2
  usage
  exit 2
fi

if ! command -v "${LOOM_BIN}" >/dev/null 2>&1; then
  echo "loom binary not found: ${LOOM_BIN}" >&2
  exit 1
fi

case "${PROFILE}" in
  openclaw)
    transports=(telegram discord whatsapp slack email webhook browser shell)
    ;;
  openfang)
    transports=(grpc a2a mcp http)
    ;;
  zeroclaw)
    transports=(telegram discord browser shell webhook ros2)
    ;;
  *)
    echo "Unsupported profile: ${PROFILE}" >&2
    echo "Supported: openclaw, openfang, zeroclaw" >&2
    exit 2
    ;;
esac

echo "[loom-migrate] profile=${PROFILE}"
echo "[loom-migrate] root=${ROOT}"
echo "[loom-migrate] kernel_path=${KERNEL_PATH}"
echo "[loom-migrate] org_id=${ORG_ID}"

root_suffix="$(printf '%s' "${ROOT}" | sha1sum | awk '{print $1}' | cut -c1-8)"
agent_label="${AGENT_NAME} ${root_suffix}"

"${LOOM_BIN}" quickstart \
  --root "${ROOT}" \
  --kernel-path "${KERNEL_PATH}" \
  --org-id "${ORG_ID}" \
  --charter "${CHARTER}" \
  --agent-name "${agent_label}" \
  --webhook-url "${WEBHOOK_URL}" \
  --non-interactive \
  --format json >/dev/null

for transport in "${transports[@]}"; do
  adapter_name="${PROFILE}-${transport}-adapter"
  adapter_id="${adapter_name}"
  echo "[loom-migrate] scaffold transport=${transport} adapter=${adapter_name}"
  "${LOOM_BIN}" connect scaffold \
    --name "${adapter_name}" \
    --transport "${transport}" \
    --action-schema meridian.runtime.v1 \
    --root "${ROOT}" \
    --format json >/dev/null
  "${LOOM_BIN}" connect enable --adapter-id "${adapter_id}" --root "${ROOT}" --format json >/dev/null
  "${LOOM_BIN}" connect test --adapter-id "${adapter_id}" --root "${ROOT}" --format json >/dev/null
  "${LOOM_BIN}" connect health --adapter-id "${adapter_id}" --root "${ROOT}" --format json >/dev/null
done

"${LOOM_BIN}" connect scorecard --root "${ROOT}" --fix --format json >/dev/null

registry_path="${ROOT}/state/connect/registry.json"
latest_path="${ROOT}/artifacts/connect/latest.json"
adapter_count="$(jq -r '.adapters | length' "${registry_path}")"

echo "[loom-migrate] status=ok profile=${PROFILE} adapters=${adapter_count}"
echo "[loom-migrate] registry_path=${registry_path}"
echo "[loom-migrate] latest_artifact=${latest_path}"
