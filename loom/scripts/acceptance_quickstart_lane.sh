#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEFAULT_LOOM_BIN="loom"
if [[ -x "${REPO_ROOT}/target/debug/loom" ]]; then
  DEFAULT_LOOM_BIN="${REPO_ROOT}/target/debug/loom"
elif [[ -x "${REPO_ROOT}/target/release/loom" ]]; then
  DEFAULT_LOOM_BIN="${REPO_ROOT}/target/release/loom"
elif [[ -x "${HOME}/.local/bin/loom" ]]; then
  DEFAULT_LOOM_BIN="${HOME}/.local/bin/loom"
fi
LOOM_BIN="${LOOM_BIN:-${DEFAULT_LOOM_BIN}}"
if ! command -v "${LOOM_BIN}" >/dev/null 2>&1 && [[ ! -x "${LOOM_BIN}" ]]; then
  echo "[ERROR] loom binary not found (LOOM_BIN=${LOOM_BIN})" >&2
  exit 127
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/loom-quickstart-lane-XXXXXX")"
RUNTIME_ROOT="${WORK_DIR}/runtime"
KERNEL_PATH="${WORK_DIR}/kernel-fixture"
OUTPUT_JSON="${WORK_DIR}/quickstart.json"
HOME_DIR="${WORK_DIR}/home"
XDG_CONFIG_DIR="${HOME_DIR}/.config"

mkdir -p "${XDG_CONFIG_DIR}"
export HOME="${HOME_DIR}"
export XDG_CONFIG_HOME="${XDG_CONFIG_DIR}"

cleanup_on_error() {
  local code=$?
  if [[ ${code} -ne 0 ]]; then
    echo "[ERROR] acceptance_quickstart_lane failed (exit=${code})" >&2
    echo "[ERROR] workspace preserved at ${WORK_DIR}" >&2
  fi
}
trap cleanup_on_error EXIT

echo "[INFO] workspace: ${WORK_DIR}"
echo "[INFO] preparing kernel fixture"
mkdir -p "${KERNEL_PATH}"
cp -R /opt/meridian-kernel/. "${KERNEL_PATH}"

detach_kernel_link() {
  local rel_path="$1"
  local dest="${KERNEL_PATH}/${rel_path}"
  if [[ ! -L "${dest}" ]]; then
    return
  fi
  local src
  src="$(readlink "${dest}")"
  rm -f "${dest}"
  if [[ -n "${src}" && -r "${src}" ]]; then
    cp "${src}" "${dest}"
    return
  fi
  case "${rel_path}" in
    kernel/agent_registry.json)
      printf '{\n  "agents": {},\n  "updatedAt": "1970-01-01T00:00:00Z"\n}\n' > "${dest}"
      ;;
    kernel/organizations.json)
      printf '{\n  "organizations": {},\n  "updatedAt": "1970-01-01T00:00:00Z"\n}\n' > "${dest}"
      ;;
    kernel/audit_log.jsonl|kernel/metering.jsonl)
      : > "${dest}"
      ;;
    kernel/authority_queue.json|kernel/court_records.json)
      printf '{}\n' > "${dest}"
      ;;
    *)
      : > "${dest}"
      ;;
  esac
}

detach_kernel_link "kernel/agent_registry.json"
detach_kernel_link "kernel/audit_log.jsonl"
detach_kernel_link "kernel/authority_queue.json"
detach_kernel_link "kernel/court_records.json"
detach_kernel_link "kernel/metering.jsonl"
detach_kernel_link "kernel/organizations.json"

echo "[INFO] running one-command quickstart lane"
"${LOOM_BIN}" quickstart \
  --root "${RUNTIME_ROOT}" \
  --kernel-path "${KERNEL_PATH}" \
  --org-id "org_quickstart_lane" \
  --charter "Quickstart Lane Charter" \
  --agent-name "Quickstart Lane Agent" \
  --webhook-url "https://example.com/quickstart-lane-webhook" \
  --channel-test-text "quickstart lane diagnostics ping" \
  --format json > "${OUTPUT_JSON}"

echo "[INFO] validating governance + proof artifacts"
python3 - "${OUTPUT_JSON}" <<'PY'
import json
import os
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)

def require(condition, message):
    if not condition:
        raise SystemExit(message)

require(payload.get("status") == "quickstart_completed", "status != quickstart_completed")
require(payload.get("steps", {}).get("nation", {}).get("status") == "init_nation_ready", "nation bootstrap missing")
require(payload.get("steps", {}).get("first_proof", {}).get("warrant_binding_status") == "verified", "first proof warrant binding is not verified")

artifacts = payload.get("artifacts", {})
for key in ("execution_path", "shadow_latest_path", "parity_report_path", "shadow_report_path", "proof_summary_path", "warrant_file_path"):
    value = artifacts.get(key, "")
    require(bool(value), f"missing artifact key: {key}")
    require(os.path.exists(value), f"artifact does not exist: {key} -> {value}")

print("=== QUICKSTART ACCEPTANCE SUMMARY ===")
print(f"status                : {payload.get('status')}")
print(f"org_id                : {payload.get('org_id')}")
print(f"agent_slug            : {payload.get('agent', {}).get('slug')}")
print(f"nation_status         : {payload.get('steps', {}).get('nation', {}).get('status')}")
print(f"warrant_binding       : {payload.get('steps', {}).get('first_proof', {}).get('warrant_binding_status')}")
print(f"execution_path        : {artifacts.get('execution_path')}")
print(f"shadow_latest_path    : {artifacts.get('shadow_latest_path')}")
print(f"parity_report_path    : {artifacts.get('parity_report_path')}")
print(f"shadow_report_path    : {artifacts.get('shadow_report_path')}")
print(f"proof_summary_path    : {artifacts.get('proof_summary_path')}")
PY

echo "[OK] acceptance_quickstart_lane passed"
