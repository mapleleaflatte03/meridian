#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load persistent local operator environment if present. This is where provider
# keys and brain_router overrides live (MERIDIAN_BRAIN_MANAGER_*, OPENAI_API_KEY,
# MERIDIAN_MANAGER_XAI_*, agent provider envs, etc.), so the workspace process
# inherits a real provider path instead of defaulting to cli_session with no
# cli_bin and failing every Team governed execution.
MERIDIAN_LOCAL_ENV_FILE="${MERIDIAN_LOCAL_ENV_FILE:-$HOME/.meridian/.env}"
if [[ -f "${MERIDIAN_LOCAL_ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${MERIDIAN_LOCAL_ENV_FILE}"
  set +a
fi
MERIDIAN_LOCAL_GATEWAY_ENV_FILE="${MERIDIAN_LOCAL_GATEWAY_ENV_FILE:-$HOME/.meridian/.env.gateway}"
if [[ -f "${MERIDIAN_LOCAL_GATEWAY_ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${MERIDIAN_LOCAL_GATEWAY_ENV_FILE}"
  set +a
fi

export MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
export MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT:-$MERIDIAN_ROOT/kernel}"
export MERIDIAN_INTELLIGENCE_ROOT="${MERIDIAN_INTELLIGENCE_ROOT:-$MERIDIAN_ROOT/intelligence}"
export MERIDIAN_INSTALL_MODE="${MERIDIAN_INSTALL_MODE:-user}"
export MERIDIAN_WORKSPACE_PORT="${MERIDIAN_WORKSPACE_PORT:-18901}"
export MERIDIAN_WORKSPACE_PEER_PORT="${MERIDIAN_WORKSPACE_PEER_PORT:-19001}"
export MERIDIAN_GATEWAY_PORT="${MERIDIAN_GATEWAY_PORT:-8266}"
export MERIDIAN_HEARTBEAT_ENABLED="${MERIDIAN_HEARTBEAT_ENABLED:-0}"
export MERIDIAN_WORKSPACE_READY_TIMEOUT="${MERIDIAN_WORKSPACE_READY_TIMEOUT:-45}"
export MERIDIAN_GATEWAY_READY_TIMEOUT="${MERIDIAN_GATEWAY_READY_TIMEOUT:-90}"
export MERIDIAN_PEER_WORKSPACE_ENABLED="${MERIDIAN_PEER_WORKSPACE_ENABLED:-1}"
export MERIDIAN_SUPERVISOR_ENABLE="${MERIDIAN_SUPERVISOR_ENABLE:-1}"
export MERIDIAN_SUPERVISOR_INTERVAL_SECONDS="${MERIDIAN_SUPERVISOR_INTERVAL_SECONDS:-5}"
export MERIDIAN_ENV_PROFILE="${MERIDIAN_ENV_PROFILE:-local}"
export MERIDIAN_FEDERATION_PEER_HOST_ID="${MERIDIAN_FEDERATION_PEER_HOST_ID:-host_org_b}"
if [[ "${MERIDIAN_ENV_PROFILE}" == "local" ]]; then
  export MERIDIAN_FEDERATION_SIGNING_SECRET="${MERIDIAN_FEDERATION_SIGNING_SECRET:-meridian_local_shared_secret}"
else
  if [[ -z "${MERIDIAN_FEDERATION_SIGNING_SECRET:-}" ]]; then
    echo "[ERROR] MERIDIAN_FEDERATION_SIGNING_SECRET is required when MERIDIAN_ENV_PROFILE=${MERIDIAN_ENV_PROFILE}" >&2
    exit 1
  fi
  export MERIDIAN_FEDERATION_SIGNING_SECRET
fi

if [[ "${MERIDIAN_ENV_PROFILE}" != "local" && "${MERIDIAN_WORKSPACE_PASSWORD:-}" == "meridian_local_operator" ]]; then
  echo "[ERROR] MERIDIAN_WORKSPACE_PASSWORD must not use local default when MERIDIAN_ENV_PROFILE=${MERIDIAN_ENV_PROFILE}" >&2
  exit 1
fi

QUIET=0
NO_SUPERVISOR=0
for arg in "$@"; do
  case "$arg" in
    --no-summary)
      QUIET=1
      ;;
    --no-supervisor)
      NO_SUPERVISOR=1
      ;;
  esac
done

RUNTIME_DIR="${MERIDIAN_ROOT}/runtime"
PID_DIR="${RUNTIME_DIR}/pids"
LOG_DIR="${RUNTIME_DIR}/logs"
WORKSPACE_CREDENTIALS_FILE="${MERIDIAN_WORKSPACE_CREDENTIALS_FILE:-${RUNTIME_DIR}/workspace_credentials}"
mkdir -p "${PID_DIR}" "${LOG_DIR}"

resolve_org_id() {
  python3 - <<'PY'
import json
import os

kernel_root = os.environ["MERIDIAN_KERNEL_ROOT"]
path = os.path.join(kernel_root, "kernel", "organizations.json")
if not os.path.exists(path):
    print("")
    raise SystemExit(0)

with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)
orgs = payload.get("organizations") or {}
for oid, org in orgs.items():
    if (org or {}).get("slug") == "meridian":
        print(oid)
        raise SystemExit(0)
print(next(iter(orgs.keys()), ""))
PY
}

resolve_workspace_org_id() {
  python3 - <<'PY'
import json
import os

workspace_root = os.environ["MERIDIAN_INTELLIGENCE_ROOT"]
path = os.path.join(workspace_root, "company", "meridian_platform", "organizations.json")
if not os.path.exists(path):
    print("")
    raise SystemExit(0)

with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)
orgs = payload.get("organizations") or {}
for oid, org in orgs.items():
    if (org or {}).get("slug") == "meridian":
        print(oid)
        raise SystemExit(0)
print(next(iter(orgs.keys()), ""))
PY
}

ensure_workspace_credentials() {
  MERIDIAN_INTELLIGENCE_ROOT="${MERIDIAN_INTELLIGENCE_ROOT}" \
  WORKSPACE_CREDENTIALS_FILE="${WORKSPACE_CREDENTIALS_FILE}" \
  MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID}" \
  MERIDIAN_WORKSPACE_PASSWORD="${MERIDIAN_WORKSPACE_PASSWORD:-meridian_local_operator}" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

org_file = Path(os.environ["MERIDIAN_INTELLIGENCE_ROOT"]) / "company" / "meridian_platform" / "organizations.json"
cred_file = Path(os.environ["WORKSPACE_CREDENTIALS_FILE"])
target_org = (os.environ.get("MERIDIAN_WORKSPACE_ORG_ID") or "").strip()
password = (os.environ.get("MERIDIAN_WORKSPACE_PASSWORD") or "").strip() or "meridian_local_operator"

org_id = target_org
owner_id = ""

if org_file.exists():
    payload = json.loads(org_file.read_text(encoding="utf-8"))
    orgs = payload.get("organizations") or {}
    if not org_id:
        for oid, org in orgs.items():
            if (org or {}).get("slug") == "meridian":
                org_id = oid
                break
    if not org_id and orgs:
        org_id = next(iter(orgs.keys()))
    org = orgs.get(org_id) or {}
    owner_id = (org.get("owner_id") or "").strip()
    if not owner_id:
        for member in org.get("members") or []:
            candidate = (member.get("user_id") or "").strip()
            if candidate:
                owner_id = candidate
                break

if not org_id or not owner_id:
    raise SystemExit("workspace credentials require an onboarding-created institution or explicit MERIDIAN_WORKSPACE_ORG_ID")

cred_file.parent.mkdir(parents=True, exist_ok=True)
cred_file.write_text(
    "\n".join(
        [
            "user: owner",
            f"pass: {password}",
            f"org_id: {org_id}",
            f"user_id: {owner_id}",
        ]
    )
    + "\n",
    encoding="utf-8",
)
os.chmod(cred_file, 0o600)
print(str(cred_file))
PY
}

export MERIDIAN_ORG_ID="${MERIDIAN_ORG_ID:-$(resolve_org_id)}"
export MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID:-$(resolve_workspace_org_id)}"
export MERIDIAN_WORKSPACE_CREDENTIALS_FILE="${WORKSPACE_CREDENTIALS_FILE}"

if [ -z "${MERIDIAN_ORG_ID}" ] || [ -z "${MERIDIAN_WORKSPACE_ORG_ID}" ]; then
  echo "[dev-up] No institution context found. Complete onboarding first or set MERIDIAN_ORG_ID and MERIDIAN_WORKSPACE_ORG_ID explicitly." >&2
  exit 1
fi

ensure_workspace_credentials >/dev/null

port_listening() {
  local port="$1"
  if command -v rg >/dev/null 2>&1; then
    ss -lnt "( sport = :${port} )" 2>/dev/null | rg -q ":${port}\\b"
  else
    ss -lnt "( sport = :${port} )" 2>/dev/null | grep -Eq ":${port}([^0-9]|$)"
  fi
}

pid_for_port() {
  local port="$1"
  ss -ltnp "( sport = :${port} )" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -n 1
}

process_cmdline() {
  local pid="$1"
  if [[ -z "${pid}" || ! -r "/proc/${pid}/cmdline" ]]; then
    return 1
  fi
  tr '\0' ' ' <"/proc/${pid}/cmdline"
}

is_legacy_workspace_process() {
  local pid="$1"
  local cmdline=""
  cmdline="$(process_cmdline "${pid}" 2>/dev/null || true)"
  [[ "${cmdline}" == *"/home/ubuntu/.meridian/workspace/"* ]]
}

kill_port_process() {
  local port="$1"
  local pids
  pids="$(ss -ltnp "( sport = :${port} )" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u | tr '\n' ' ')"
  if [[ -z "${pids// }" ]]; then
    return
  fi
  for pid in ${pids}; do
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
      sleep 0.2
      kill -9 "${pid}" >/dev/null 2>&1 || true
    fi
  done
}

kill_pid_file_process() {
  local name="$1"
  local pid_file="${PID_DIR}/${name}.pid"
  if [[ ! -f "${pid_file}" ]]; then
    return
  fi
  local pid
  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    kill "${pid}" >/dev/null 2>&1 || true
    sleep 0.3
    kill -9 "${pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${pid_file}"
}

disable_legacy_gateway_unit_if_needed() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return
  fi
  if ! systemctl --user list-unit-files 2>/dev/null | grep -q '^meridian-gateway.service'; then
    return
  fi
  local unit_body
  unit_body="$(systemctl --user cat meridian-gateway.service 2>/dev/null || true)"
  if [[ "${unit_body}" != *"/home/ubuntu/.meridian/workspace/meridian_gateway.py"* ]]; then
    return
  fi
  echo "[dev-up] disabling legacy user unit meridian-gateway.service (points to ~/.meridian/workspace)"
  systemctl --user disable --now meridian-gateway.service >/dev/null 2>&1 || true
}

print_startup_failure() {
  local name="$1"
  local log_file="$2"
  echo "[dev-up] ${name} failed to start after retries"
  if [[ -f "${log_file}" ]]; then
    echo "[dev-up] --- tail ${log_file} ---"
    tail -n 120 "${log_file}" || true
    echo "[dev-up] --- end tail ---"
  fi
}

wait_for_json() {
  local url="$1"
  local timeout_s="${2:-30}"
  python3 - "$url" "$timeout_s" <<'PY'
import json
import sys
import time
import urllib.request

url = sys.argv[1]
timeout_s = float(sys.argv[2])
deadline = time.time() + timeout_s
last = None
while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=min(timeout_s, 8.0)) as r:
            payload = json.loads(r.read().decode("utf-8"))
        print(json.dumps(payload))
        raise SystemExit(0)
    except Exception as exc:  # noqa: BLE001
        last = exc
        time.sleep(0.5)
raise SystemExit(f"timeout waiting for {url}: {last}")
PY
}

service_healthy() {
  local url="$1"
  local timeout_s="${2:-5}"
  python3 - "$url" "$timeout_s" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
timeout_s = float(sys.argv[2])
try:
    with urllib.request.urlopen(url, timeout=timeout_s) as r:
        payload = json.loads(r.read().decode("utf-8"))
    if isinstance(payload, dict):
        raise SystemExit(0)
except Exception:
    raise SystemExit(1)
PY
}

resolve_primary_host_id() {
  local manifest_json host_id
  manifest_json="$(wait_for_json "http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}/api/federation/manifest" "${MERIDIAN_WORKSPACE_READY_TIMEOUT}")"
  host_id="$(printf '%s' "${manifest_json}" | python3 -c "
import json,sys
try:
    payload=json.load(sys.stdin)
except Exception:
    print('')
    raise SystemExit(0)
host=((payload.get('host_identity') or {}).get('host_id') or '').strip()
print(host)
" 2>/dev/null || true)"
  if [[ -n "${host_id}" ]]; then
    printf '%s' "${host_id}"
    return
  fi
  python3 - <<'PY'
import socket
raw = socket.gethostname().strip().lower() or 'live'
safe = ''.join(ch if ch.isalnum() else '_' for ch in raw).strip('_') or 'live'
print(f"host_{safe}")
PY
}

write_peer_runtime_files() {
  local primary_host_id="$1"
  local peer_root="${RUNTIME_DIR}/federation_peer"
  local peer_host_id="${MERIDIAN_FEDERATION_PEER_HOST_ID}"
  mkdir -p "${peer_root}"
  PRIMARY_HOST_ID="${primary_host_id}" \
  PEER_HOST_ID="${peer_host_id}" \
  PEER_PORT="${MERIDIAN_WORKSPACE_PEER_PORT}" \
  PRIMARY_PORT="${MERIDIAN_WORKSPACE_PORT}" \
  WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID}" \
  FEDERATION_SIGNING_SECRET="${MERIDIAN_FEDERATION_SIGNING_SECRET}" \
  PEER_ROOT="${peer_root}" \
  python3 - <<'PY'
import json
import os

peer_root = os.environ["PEER_ROOT"]
peer_host_id = os.environ["PEER_HOST_ID"]
primary_host_id = os.environ["PRIMARY_HOST_ID"]
peer_port = int(os.environ["PEER_PORT"])
primary_port = int(os.environ["PRIMARY_PORT"])
workspace_org_id = (os.environ.get("WORKSPACE_ORG_ID") or "").strip()
secret = (os.environ.get("FEDERATION_SIGNING_SECRET") or "").strip()

def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)

host_identity = {
    "host_id": peer_host_id,
    "label": "Meridian Peer Host B",
    "role": "institution_host",
    "federation_enabled": True,
    "peer_transport": "http",
    "supported_boundaries": ["workspace", "federation_gateway"],
    "settlement_adapters": ["internal_ledger"],
}
admissions = {
    "host_id": peer_host_id,
    "institutions": {
        workspace_org_id: {
            "status": "admitted",
            "source": "dev_stack_supervisor",
        }
    } if workspace_org_id else {},
}
peers = {
    "host_id": peer_host_id,
    "peers": {
        primary_host_id: {
            "host_id": primary_host_id,
            "label": "Meridian Primary Host",
            "transport": "http",
            "endpoint_url": f"http://127.0.0.1:{primary_port}",
            "trust_state": "trusted",
            "shared_secret": secret,
            "admitted_org_ids": [workspace_org_id] if workspace_org_id else [],
            "capability_snapshot": {},
            "last_refreshed_at": "",
        }
    },
}
witness_archive = {
    "host_id": peer_host_id,
    "observations": [],
}
write_json(os.path.join(peer_root, "host_identity.json"), host_identity)
write_json(os.path.join(peer_root, "institution_admissions.json"), admissions)
write_json(os.path.join(peer_root, "federation_peers.json"), peers)
write_json(os.path.join(peer_root, "witness_archive.json"), witness_archive)
open(os.path.join(peer_root, ".federation_replay"), "a", encoding="utf-8").close()
PY
}
start_workspace_if_needed() {
  if port_listening "$MERIDIAN_WORKSPACE_PORT"; then
    local existing_pid=""
    existing_pid="$(pid_for_port "${MERIDIAN_WORKSPACE_PORT}")"
    if [[ -n "${existing_pid}" ]] && is_legacy_workspace_process "${existing_pid}"; then
      echo "[dev-up] workspace port ${MERIDIAN_WORKSPACE_PORT} owned by legacy runtime (pid=${existing_pid}); restarting"
      kill_port_process "${MERIDIAN_WORKSPACE_PORT}"
    elif service_healthy "http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}/api/healthz" 8; then
      echo "[dev-up] workspace already listening on :${MERIDIAN_WORKSPACE_PORT}"
      return
    else
      echo "[dev-up] workspace port ${MERIDIAN_WORKSPACE_PORT} is stale; restarting"
      kill_port_process "${MERIDIAN_WORKSPACE_PORT}"
    fi
  fi

  local attempts=3
  local attempt=1
  while [[ "${attempt}" -le "${attempts}" ]]; do
    echo "[dev-up] starting workspace on :${MERIDIAN_WORKSPACE_PORT} (attempt ${attempt}/${attempts})"
    kill_pid_file_process "workspace"
    (
      cd "${MERIDIAN_INTELLIGENCE_ROOT}/company/meridian_platform"
      local org_args=()
      if [[ -n "${MERIDIAN_WORKSPACE_ORG_ID}" ]]; then
        org_args=(--org-id "${MERIDIAN_WORKSPACE_ORG_ID}")
      fi
      MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" \
      MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID}" \
      MERIDIAN_WORKSPACE_CREDENTIALS_FILE="${MERIDIAN_WORKSPACE_CREDENTIALS_FILE}" \
      MERIDIAN_FEDERATION_SIGNING_SECRET="${MERIDIAN_FEDERATION_SIGNING_SECRET}" \
      nohup python3 workspace.py --port "${MERIDIAN_WORKSPACE_PORT}" "${org_args[@]}" \
        >"${LOG_DIR}/workspace.log" 2>&1 &
      echo $! > "${PID_DIR}/workspace.pid"
    )
    local workspace_pid=""
    workspace_pid="$(cat "${PID_DIR}/workspace.pid" 2>/dev/null || true)"
    for _ in $(seq 1 30); do
      if port_listening "${MERIDIAN_WORKSPACE_PORT}"; then
        return
      fi
      if [[ -n "${workspace_pid}" ]] && ! kill -0 "${workspace_pid}" >/dev/null 2>&1; then
        break
      fi
      sleep 0.5
    done
    attempt=$((attempt + 1))
  done

  print_startup_failure "workspace" "${LOG_DIR}/workspace.log"
  return 1
}

start_workspace_peer_if_needed() {
  if [[ "${MERIDIAN_PEER_WORKSPACE_ENABLED}" != "1" ]]; then
    return
  fi

  if port_listening "$MERIDIAN_WORKSPACE_PEER_PORT"; then
    local existing_pid=""
    existing_pid="$(pid_for_port "${MERIDIAN_WORKSPACE_PEER_PORT}")"
    if [[ -n "${existing_pid}" ]] && is_legacy_workspace_process "${existing_pid}"; then
      echo "[dev-up] workspace peer port ${MERIDIAN_WORKSPACE_PEER_PORT} owned by legacy runtime (pid=${existing_pid}); restarting"
      kill_port_process "${MERIDIAN_WORKSPACE_PEER_PORT}"
    elif wait_for_json "http://127.0.0.1:${MERIDIAN_WORKSPACE_PEER_PORT}/api/healthz" 8 >/dev/null 2>&1; then
      echo "[dev-up] workspace peer already listening on :${MERIDIAN_WORKSPACE_PEER_PORT}"
      return
    else
      echo "[dev-up] workspace peer port ${MERIDIAN_WORKSPACE_PEER_PORT} is stale; restarting"
      kill_port_process "${MERIDIAN_WORKSPACE_PEER_PORT}"
    fi
  fi

  local primary_host_id
  primary_host_id="$(resolve_primary_host_id)"
  write_peer_runtime_files "${primary_host_id}"

  local peer_root="${RUNTIME_DIR}/federation_peer"
  local attempts=3
  local attempt=1
  while [[ "${attempt}" -le "${attempts}" ]]; do
    echo "[dev-up] starting workspace peer on :${MERIDIAN_WORKSPACE_PEER_PORT} (attempt ${attempt}/${attempts})"
    kill_pid_file_process "workspace-peer"
    (
      cd "${MERIDIAN_INTELLIGENCE_ROOT}/company/meridian_platform"
      local org_args=()
      if [[ -n "${MERIDIAN_WORKSPACE_ORG_ID}" ]]; then
        org_args=(--org-id "${MERIDIAN_WORKSPACE_ORG_ID}")
      fi
      MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" \
      MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID}" \
      MERIDIAN_WORKSPACE_CREDENTIALS_FILE="${MERIDIAN_WORKSPACE_CREDENTIALS_FILE}" \
      MERIDIAN_RUNTIME_HOST_IDENTITY_FILE="${peer_root}/host_identity.json" \
      MERIDIAN_RUNTIME_ADMISSION_FILE="${peer_root}/institution_admissions.json" \
      MERIDIAN_FEDERATION_PEERS_FILE="${peer_root}/federation_peers.json" \
      MERIDIAN_FEDERATION_REPLAY_FILE="${peer_root}/.federation_replay" \
      MERIDIAN_WITNESS_ARCHIVE_FILE="${peer_root}/witness_archive.json" \
      MERIDIAN_FEDERATION_SIGNING_SECRET="${MERIDIAN_FEDERATION_SIGNING_SECRET}" \
      nohup python3 workspace.py --port "${MERIDIAN_WORKSPACE_PEER_PORT}" "${org_args[@]}" \
        >"${LOG_DIR}/workspace-peer.log" 2>&1 &
      echo $! > "${PID_DIR}/workspace-peer.pid"
    )
    local peer_pid=""
    peer_pid="$(cat "${PID_DIR}/workspace-peer.pid" 2>/dev/null || true)"
    for _ in $(seq 1 30); do
      if port_listening "${MERIDIAN_WORKSPACE_PEER_PORT}"; then
        if wait_for_json "http://127.0.0.1:${MERIDIAN_WORKSPACE_PEER_PORT}/api/healthz" 8 >/dev/null 2>&1; then
          return
        fi
      fi
      if [[ -n "${peer_pid}" ]] && ! kill -0 "${peer_pid}" >/dev/null 2>&1; then
        break
      fi
      sleep 0.5
    done
    attempt=$((attempt + 1))
  done

  print_startup_failure "workspace-peer" "${LOG_DIR}/workspace-peer.log"
  return 1
}

start_gateway_if_needed() {
  if port_listening "$MERIDIAN_GATEWAY_PORT"; then
    local existing_pid=""
    existing_pid="$(pid_for_port "${MERIDIAN_GATEWAY_PORT}")"
    if [[ -n "${existing_pid}" ]] && is_legacy_workspace_process "${existing_pid}"; then
      echo "[dev-up] gateway port ${MERIDIAN_GATEWAY_PORT} owned by legacy runtime (pid=${existing_pid}); restarting"
      kill_port_process "${MERIDIAN_GATEWAY_PORT}"
    elif service_healthy "http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}/api/healthz" 8; then
      echo "[dev-up] gateway already listening on :${MERIDIAN_GATEWAY_PORT}"
      return
    else
      echo "[dev-up] gateway port ${MERIDIAN_GATEWAY_PORT} is stale; restarting"
      kill_port_process "${MERIDIAN_GATEWAY_PORT}"
    fi
  fi

  local attempts=3
  local attempt=1
  while [[ "${attempt}" -le "${attempts}" ]]; do
    echo "[dev-up] starting gateway on :${MERIDIAN_GATEWAY_PORT} (attempt ${attempt}/${attempts})"
    kill_pid_file_process "gateway"
    (
      cd "${MERIDIAN_INTELLIGENCE_ROOT}"
      MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" \
      MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID}" \
      MERIDIAN_WORKSPACE_CREDENTIALS_FILE="${MERIDIAN_WORKSPACE_CREDENTIALS_FILE}" \
      MERIDIAN_WORKSPACE_API_BASE="http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}" \
      MERIDIAN_GATEWAY_PORT="${MERIDIAN_GATEWAY_PORT}" \
      MERIDIAN_HEARTBEAT_ENABLED="${MERIDIAN_HEARTBEAT_ENABLED}" \
      nohup python3 meridian_gateway.py >"${LOG_DIR}/gateway.log" 2>&1 &
      echo $! > "${PID_DIR}/gateway.pid"
    )
    local gateway_pid=""
    gateway_pid="$(cat "${PID_DIR}/gateway.pid" 2>/dev/null || true)"
    for _ in $(seq 1 40); do
      if port_listening "${MERIDIAN_GATEWAY_PORT}"; then
        return
      fi
      if [[ -n "${gateway_pid}" ]] && ! kill -0 "${gateway_pid}" >/dev/null 2>&1; then
        break
      fi
      sleep 0.5
    done
    attempt=$((attempt + 1))
  done

  print_startup_failure "gateway" "${LOG_DIR}/gateway.log"
  return 1
}

start_supervisor_if_needed() {
  if [[ "${MERIDIAN_SUPERVISOR_ENABLE}" != "1" || "${NO_SUPERVISOR}" == "1" ]]; then
    return
  fi

  local pid_file="${PID_DIR}/supervisor.pid"
  if [[ -f "${pid_file}" ]]; then
    local existing_pid
    existing_pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" >/dev/null 2>&1; then
      echo "[dev-up] supervisor already running (pid=${existing_pid})"
      return
    fi
    rm -f "${pid_file}"
  fi

  echo "[dev-up] starting supervisor loop for ports ${MERIDIAN_WORKSPACE_PORT}/${MERIDIAN_WORKSPACE_PEER_PORT}/${MERIDIAN_GATEWAY_PORT}"
  (
    cd "${MERIDIAN_ROOT}"
    MERIDIAN_ROOT="${MERIDIAN_ROOT}" \
    MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" \
    MERIDIAN_INTELLIGENCE_ROOT="${MERIDIAN_INTELLIGENCE_ROOT}" \
    MERIDIAN_WORKSPACE_PORT="${MERIDIAN_WORKSPACE_PORT}" \
    MERIDIAN_WORKSPACE_PEER_PORT="${MERIDIAN_WORKSPACE_PEER_PORT}" \
    MERIDIAN_GATEWAY_PORT="${MERIDIAN_GATEWAY_PORT}" \
    MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID}" \
    MERIDIAN_WORKSPACE_CREDENTIALS_FILE="${MERIDIAN_WORKSPACE_CREDENTIALS_FILE}" \
    MERIDIAN_HEARTBEAT_ENABLED="${MERIDIAN_HEARTBEAT_ENABLED}" \
    MERIDIAN_PEER_WORKSPACE_ENABLED="${MERIDIAN_PEER_WORKSPACE_ENABLED}" \
    MERIDIAN_SUPERVISOR_INTERVAL_SECONDS="${MERIDIAN_SUPERVISOR_INTERVAL_SECONDS}" \
    MERIDIAN_FEDERATION_PEER_HOST_ID="${MERIDIAN_FEDERATION_PEER_HOST_ID}" \
    MERIDIAN_FEDERATION_SIGNING_SECRET="${MERIDIAN_FEDERATION_SIGNING_SECRET}" \
    nohup "${MERIDIAN_ROOT}/scripts/dev-supervisor.sh" run >"${LOG_DIR}/supervisor.log" 2>&1 &
    echo $! > "${PID_DIR}/supervisor.pid"
  )
}

disable_legacy_gateway_unit_if_needed
start_workspace_if_needed
wait_for_json "http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}/api/healthz" "${MERIDIAN_WORKSPACE_READY_TIMEOUT}" >/dev/null
start_workspace_peer_if_needed

start_gateway_if_needed
STATUS_JSON="$(wait_for_json "http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}/api/status" "${MERIDIAN_GATEWAY_READY_TIMEOUT}")"
TEMPLATE_JSON="$(wait_for_json "http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}/api/institution/template" "${MERIDIAN_GATEWAY_READY_TIMEOUT}")"
TREASURY_JSON="$(wait_for_json "http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}/api/treasury" "${MERIDIAN_GATEWAY_READY_TIMEOUT}")"
export STATUS_JSON TEMPLATE_JSON TREASURY_JSON
start_supervisor_if_needed

if [[ "$QUIET" -eq 0 ]]; then
  python3 - <<'PY'
import json
import os

status = json.loads(os.environ["STATUS_JSON"])
template = json.loads(os.environ["TEMPLATE_JSON"])
treasury = json.loads(os.environ["TREASURY_JSON"])
print(json.dumps({
    "status": "ok",
    "org_id": (status.get("context") or {}).get("bound_org_id"),
    "runtime_id": status.get("runtime_id"),
    "slo_status": (status.get("slo") or {}).get("status"),
    "institution_template_schema": template.get("schema_version"),
    "court_rule_count": len(template.get("court_rule_set") or []),
    "treasury_balance_usd": treasury.get("balance_usd"),
    "treasury_reserve_floor_usd": treasury.get("reserve_floor_usd"),
    "routes": {
        "status": "http://127.0.0.1:%s/api/status" % os.environ["MERIDIAN_GATEWAY_PORT"],
        "proofs": "http://127.0.0.1:%s/proofs" % os.environ["MERIDIAN_GATEWAY_PORT"],
        "workflows": "http://127.0.0.1:%s/workflows" % os.environ["MERIDIAN_GATEWAY_PORT"],
    },
}, indent=2))
PY
fi

echo "[dev-up] stack ready (org=${MERIDIAN_ORG_ID})"
