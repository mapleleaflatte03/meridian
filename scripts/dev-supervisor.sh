#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
export MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT:-$MERIDIAN_ROOT/kernel}"
export MERIDIAN_INTELLIGENCE_ROOT="${MERIDIAN_INTELLIGENCE_ROOT:-$MERIDIAN_ROOT/intelligence}"
export MERIDIAN_WORKSPACE_PORT="${MERIDIAN_WORKSPACE_PORT:-18901}"
export MERIDIAN_WORKSPACE_PEER_PORT="${MERIDIAN_WORKSPACE_PEER_PORT:-19001}"
export MERIDIAN_GATEWAY_PORT="${MERIDIAN_GATEWAY_PORT:-8266}"
export MERIDIAN_SUPERVISOR_INTERVAL_SECONDS="${MERIDIAN_SUPERVISOR_INTERVAL_SECONDS:-5}"
export MERIDIAN_PEER_WORKSPACE_ENABLED="${MERIDIAN_PEER_WORKSPACE_ENABLED:-1}"
export MERIDIAN_FEDERATION_PEER_HOST_ID="${MERIDIAN_FEDERATION_PEER_HOST_ID:-host_org_b}"
export MERIDIAN_FEDERATION_SIGNING_SECRET="${MERIDIAN_FEDERATION_SIGNING_SECRET:-meridian_local_shared_secret}"

RUNTIME_DIR="${MERIDIAN_ROOT}/runtime"
PID_DIR="${RUNTIME_DIR}/pids"
LOG_DIR="${RUNTIME_DIR}/logs"
mkdir -p "${PID_DIR}" "${LOG_DIR}"

SUPERVISOR_PID_FILE="${PID_DIR}/supervisor.pid"
SUPERVISOR_LOCK_FILE="${PID_DIR}/supervisor.lock"

port_listening() {
  local port="$1"
  ss -lnt "( sport = :${port} )" 2>/dev/null | grep -Eq ":${port}([^0-9]|$)"
}

http_ok() {
  local url="$1"
  python3 - "$url" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=4.0) as r:
        payload = json.loads(r.read().decode("utf-8"))
    if isinstance(payload, dict):
        raise SystemExit(0)
except Exception:
    pass
raise SystemExit(1)
PY
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
    sleep 0.2
    kill -9 "${pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${pid_file}"
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

resolve_primary_host_id() {
  python3 - "$MERIDIAN_WORKSPACE_PORT" <<'PY'
import json
import socket
import sys
import urllib.request

port = int(sys.argv[1])
url = f"http://127.0.0.1:{port}/api/federation/manifest"
host_id = ""
try:
    with urllib.request.urlopen(url, timeout=4.0) as r:
        payload = json.loads(r.read().decode("utf-8"))
    host_id = ((payload.get("host_identity") or {}).get("host_id") or "").strip()
except Exception:
    host_id = ""
if not host_id:
    raw = socket.gethostname().strip().lower() or "live"
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw).strip("_") or "live"
    host_id = f"host_{safe}"
print(host_id)
PY
}

write_peer_runtime_files() {
  local primary_host_id="$1"
  local peer_root="${RUNTIME_DIR}/federation_peer"
  local peer_host_id="${MERIDIAN_FEDERATION_PEER_HOST_ID}"
  local workspace_org_id="${MERIDIAN_WORKSPACE_ORG_ID:-}"
  if [[ -z "${workspace_org_id}" ]]; then
    workspace_org_id="$(resolve_workspace_org_id)"
  fi
  mkdir -p "${peer_root}"
  PRIMARY_HOST_ID="${primary_host_id}" \
  PEER_HOST_ID="${peer_host_id}" \
  PRIMARY_PORT="${MERIDIAN_WORKSPACE_PORT}" \
  WORKSPACE_ORG_ID="${workspace_org_id}" \
  FEDERATION_SIGNING_SECRET="${MERIDIAN_FEDERATION_SIGNING_SECRET}" \
  PEER_ROOT="${peer_root}" \
  python3 - <<'PY'
import json
import os

peer_root = os.environ["PEER_ROOT"]
peer_host_id = os.environ["PEER_HOST_ID"]
primary_host_id = os.environ["PRIMARY_HOST_ID"]
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
            "source": "dev_supervisor",
        }
    } if workspace_org_id else {},
}
peer_registry = {
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
witness_archive = {"host_id": peer_host_id, "observations": []}

write_json(os.path.join(peer_root, "host_identity.json"), host_identity)
write_json(os.path.join(peer_root, "institution_admissions.json"), admissions)
write_json(os.path.join(peer_root, "federation_peers.json"), peer_registry)
write_json(os.path.join(peer_root, "witness_archive.json"), witness_archive)
open(os.path.join(peer_root, ".federation_replay"), "a", encoding="utf-8").close()
PY
}

start_workspace() {
  kill_pid_file_process "workspace"
  local workspace_org_id="${MERIDIAN_WORKSPACE_ORG_ID:-}"
  if [[ -z "${workspace_org_id}" ]]; then
    workspace_org_id="$(resolve_workspace_org_id)"
  fi
  (
    cd "${MERIDIAN_INTELLIGENCE_ROOT}/company/meridian_platform"
    local org_args=()
    if [[ -n "${workspace_org_id}" ]]; then
      org_args=(--org-id "${workspace_org_id}")
    fi
    MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" \
    MERIDIAN_WORKSPACE_ORG_ID="${workspace_org_id}" \
    nohup python3 workspace.py --port "${MERIDIAN_WORKSPACE_PORT}" "${org_args[@]}" \
      >"${LOG_DIR}/workspace.log" 2>&1 &
    echo $! > "${PID_DIR}/workspace.pid"
  )
}

start_workspace_peer() {
  if [[ "${MERIDIAN_PEER_WORKSPACE_ENABLED}" != "1" ]]; then
    return
  fi
  local primary_host_id workspace_org_id peer_root
  primary_host_id="$(resolve_primary_host_id)"
  workspace_org_id="${MERIDIAN_WORKSPACE_ORG_ID:-}"
  if [[ -z "${workspace_org_id}" ]]; then
    workspace_org_id="$(resolve_workspace_org_id)"
  fi
  write_peer_runtime_files "${primary_host_id}"
  peer_root="${RUNTIME_DIR}/federation_peer"
  kill_pid_file_process "workspace-peer"
  (
    cd "${MERIDIAN_INTELLIGENCE_ROOT}/company/meridian_platform"
    local org_args=()
    if [[ -n "${workspace_org_id}" ]]; then
      org_args=(--org-id "${workspace_org_id}")
    fi
    MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" \
    MERIDIAN_WORKSPACE_ORG_ID="${workspace_org_id}" \
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
}

start_gateway() {
  kill_pid_file_process "gateway"
  (
    cd "${MERIDIAN_INTELLIGENCE_ROOT}"
    MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" \
    MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID:-}" \
    MERIDIAN_WORKSPACE_API_BASE="http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}" \
    MERIDIAN_GATEWAY_PORT="${MERIDIAN_GATEWAY_PORT}" \
    nohup python3 meridian_gateway.py >"${LOG_DIR}/gateway.log" 2>&1 &
    echo $! > "${PID_DIR}/gateway.pid"
  )
}

status() {
  for pair in "workspace:${MERIDIAN_WORKSPACE_PORT}" "workspace-peer:${MERIDIAN_WORKSPACE_PEER_PORT}" "gateway:${MERIDIAN_GATEWAY_PORT}"; do
    local name="${pair%%:*}"
    local port="${pair##*:}"
    if port_listening "${port}"; then
      echo "${name} : up (${port})"
    else
      echo "${name} : down (${port})"
    fi
  done
}

run_loop() {
  exec 200>"${SUPERVISOR_LOCK_FILE}"
  if ! flock -n 200; then
    echo "[supervisor] another instance is already running; exiting"
    exit 0
  fi
  echo "$$" > "${SUPERVISOR_PID_FILE}"
  trap 'rm -f "${SUPERVISOR_PID_FILE}"; exit 0' INT TERM EXIT

  echo "[supervisor] started pid=$$ interval=${MERIDIAN_SUPERVISOR_INTERVAL_SECONDS}s"
  while true; do
    if ! port_listening "${MERIDIAN_WORKSPACE_PORT}" || ! http_ok "http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}/api/status"; then
      echo "[supervisor] restarting workspace:${MERIDIAN_WORKSPACE_PORT}"
      start_workspace || true
      sleep 1
    fi

    if [[ "${MERIDIAN_PEER_WORKSPACE_ENABLED}" == "1" ]]; then
      if ! port_listening "${MERIDIAN_WORKSPACE_PEER_PORT}" || ! http_ok "http://127.0.0.1:${MERIDIAN_WORKSPACE_PEER_PORT}/api/federation/manifest"; then
        echo "[supervisor] restarting workspace-peer:${MERIDIAN_WORKSPACE_PEER_PORT}"
        start_workspace_peer || true
        sleep 1
      fi
    fi

    if ! port_listening "${MERIDIAN_GATEWAY_PORT}" || ! http_ok "http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}/api/status"; then
      echo "[supervisor] restarting gateway:${MERIDIAN_GATEWAY_PORT}"
      start_gateway || true
      sleep 1
    fi

    sleep "${MERIDIAN_SUPERVISOR_INTERVAL_SECONDS}"
  done
}

case "${MODE}" in
  run)
    run_loop
    ;;
  status)
    status
    ;;
  stop)
    kill_pid_file_process "supervisor"
    ;;
  *)
    echo "usage: $0 {run|status|stop}" >&2
    exit 2
    ;;
esac
