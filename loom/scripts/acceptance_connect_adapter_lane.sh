#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <adapter-name> <transport>" >&2
  echo "example: $0 telegram_adapter telegram" >&2
  exit 2
fi

ADAPTER_NAME="$1"
TRANSPORT="$2"
ADAPTER_ID="${ADAPTER_NAME//_/-}"

TMP_DIR="$(mktemp -d /tmp/loom_connect_adapter_lane.XXXXXX)"
trap 'rm -rf "${TMP_DIR}"' EXIT

HOME_DIR="${TMP_DIR}/home"
ROOT_DIR="${HOME_DIR}/.local/share/meridian-loom/runtime/default"
KERNEL_DIR="${TMP_DIR}/kernel"
mkdir -p "${HOME_DIR}" "${KERNEL_DIR}/kernel"

cat > "${KERNEL_DIR}/kernel/runtimes.json" <<'JSON'
{
  "runtimes": {
    "local_kernel": { "id": "local_kernel", "label": "Local Kernel Runtime" },
    "loom_native": {
      "status": "official",
      "notes": "connect adapter acceptance lane",
      "contract_compliance": {
        "agent_identity": true,
        "action_envelope": true,
        "cost_attribution": true,
        "approval_hook": true,
        "audit_emission": true,
        "sanction_controls": true,
        "budget_gate": true
      }
    }
  }
}
JSON

cat > "${KERNEL_DIR}/kernel/agent_registry.py" <<'PY'
import json
import sys
agent_id = sys.argv[sys.argv.index("--agent_id") + 1]
org_id = sys.argv[sys.argv.index("--org_id") + 1] if "--org_id" in sys.argv else "org_demo"
print(json.dumps({
    "id": agent_id,
    "name": "Atlas",
    "org_id": org_id,
    "role": "analyst",
    "economy_key": "atlas",
    "approval_required": False,
    "budget": {"max_per_run_usd": 1.0},
    "runtime_binding": {
        "runtime_id": "loom_native",
        "runtime_label": "Loom Native Runtime",
        "bound_org_id": org_id,
        "boundary_name": "workspace",
        "identity_model": "session",
        "runtime_registered": True,
        "registration_status": "registered"
    }
}, indent=2))
PY

cat > "${KERNEL_DIR}/kernel/court.py" <<'PY'
def get_restrictions(agent_id, org_id=None):
    return []
PY

cat > "${KERNEL_DIR}/kernel/authority.py" <<'PY'
def check_authority(agent_id, action, org_id=None):
    return True, "ok"
PY

echo "[loom-acceptance] adapter=${ADAPTER_ID} transport=${TRANSPORT}"
(cd "${REPO_ROOT}" && cargo build -p meridian-loom --quiet)
LOOM_BIN="${REPO_ROOT}/target/debug/loom"

export HOME="${HOME_DIR}"
export XDG_CONFIG_HOME="${HOME_DIR}/.config"
mkdir -p "${XDG_CONFIG_HOME}"

run_loom() {
  "${LOOM_BIN}" "$@"
}

run_loom_json() {
  run_loom "$@" --format json
}

run_loom init --mode embedded --root "${ROOT_DIR}" --kernel-path "${KERNEL_DIR}" --org-id org_demo >/dev/null

run_loom_json connect scaffold --name "${ADAPTER_NAME}" --transport "${TRANSPORT}" --action-schema meridian.runtime.v1 --root "${ROOT_DIR}" >/dev/null
run_loom_json connect validate --adapter-id "${ADAPTER_ID}" --root "${ROOT_DIR}" >/dev/null
run_loom_json connect enable --adapter-id "${ADAPTER_ID}" --root "${ROOT_DIR}" >/dev/null
run_loom_json connect test --adapter-id "${ADAPTER_ID}" --root "${ROOT_DIR}" >/dev/null
run_loom_json connect health --adapter-id "${ADAPTER_ID}" --root "${ROOT_DIR}" >/dev/null
run_loom_json connect diagnostics --adapter-id "${ADAPTER_ID}" --limit 10 --root "${ROOT_DIR}" >/dev/null

set +e
FAIL_OUTPUT="$(run_loom_json connect disable --adapter-id "${ADAPTER_ID}" --root "${ROOT_DIR}" 2>&1)"
DISABLE_STATUS=$?
set -e
if [[ ${DISABLE_STATUS} -ne 0 ]]; then
  echo "disable step failed for ${ADAPTER_ID}" >&2
  echo "${FAIL_OUTPUT}" >&2
  exit 1
fi

set +e
FAIL_OUTPUT="$(run_loom_json connect test --adapter-id "${ADAPTER_ID}" --root "${ROOT_DIR}" 2>&1)"
FAIL_STATUS=$?
set -e
if [[ ${FAIL_STATUS} -eq 0 ]]; then
  echo "expected disabled adapter test failure for ${ADAPTER_ID}" >&2
  exit 1
fi
if [[ "${FAIL_OUTPUT}" != *"adapter_disabled"* ]]; then
  echo "expected adapter_disabled failure for ${ADAPTER_ID}, got:" >&2
  echo "${FAIL_OUTPUT}" >&2
  exit 1
fi

HEALTH_PATH="${ROOT_DIR}/state/connect/health/${ADAPTER_ID}.json"
TESTS_PATH="${ROOT_DIR}/state/connect/tests/${ADAPTER_ID}.jsonl"
LIFECYCLE_PATH="${ROOT_DIR}/state/connect/lifecycle/${ADAPTER_ID}.jsonl"
DESKTOP_PATH="${ROOT_DIR}/state/connect/desktop/${ADAPTER_ID}.jsonl"
LATEST_PATH="${ROOT_DIR}/artifacts/connect/latest.json"

[[ -f "${HEALTH_PATH}" ]] || { echo "missing health snapshot: ${HEALTH_PATH}" >&2; exit 1; }
[[ -f "${TESTS_PATH}" ]] || { echo "missing tests history: ${TESTS_PATH}" >&2; exit 1; }
[[ -f "${LIFECYCLE_PATH}" ]] || { echo "missing lifecycle history: ${LIFECYCLE_PATH}" >&2; exit 1; }
[[ -f "${LATEST_PATH}" ]] || { echo "missing latest connect artifact: ${LATEST_PATH}" >&2; exit 1; }
if [[ "${TRANSPORT}" == "desktop" ]]; then
  [[ -f "${DESKTOP_PATH}" ]] || { echo "missing desktop history: ${DESKTOP_PATH}" >&2; exit 1; }
fi

python3 - <<'PY' "${HEALTH_PATH}" "${LATEST_PATH}" "${ADAPTER_ID}" "${TRANSPORT}" "${DESKTOP_PATH}"
import json
import pathlib
import sys

health_path = pathlib.Path(sys.argv[1])
latest_path = pathlib.Path(sys.argv[2])
adapter_id = sys.argv[3]
transport = sys.argv[4]
desktop_path = pathlib.Path(sys.argv[5])

health = json.loads(health_path.read_text())
if health.get("adapter_id") != adapter_id:
    raise SystemExit(f"health adapter mismatch: {health.get('adapter_id')} != {adapter_id}")
if not health.get("lifecycle_state"):
    raise SystemExit("health snapshot missing lifecycle_state")

latest = json.loads(latest_path.read_text())
if latest.get("adapter_id") != adapter_id:
    raise SystemExit(f"latest artifact adapter mismatch: {latest.get('adapter_id')} != {adapter_id}")
if latest.get("status") not in {"connect_tested", "connect_health", "connect_diagnostics", "connect_enabled", "connect_disabled", "connect_validated", "connect_scaffolded"}:
    raise SystemExit(f"unexpected latest status: {latest.get('status')}")

if transport == "desktop":
    lines = [line for line in desktop_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise SystemExit("desktop history is empty")
    event = json.loads(lines[-1])
    if event.get("vision_schema") != "meridian.desktop.vision.v1":
        raise SystemExit(f"unexpected vision schema: {event.get('vision_schema')}")
    digest = str(event.get("capture_digest_hex") or "")
    if len(digest) != 64:
        raise SystemExit(f"invalid desktop capture digest: {digest}")
PY

echo "[loom-acceptance] PASS adapter lane ${ADAPTER_ID} (${TRANSPORT})"
