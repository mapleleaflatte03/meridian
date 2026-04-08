#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
export MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT:-$MERIDIAN_ROOT/kernel}"
export MERIDIAN_INTELLIGENCE_ROOT="${MERIDIAN_INTELLIGENCE_ROOT:-$MERIDIAN_ROOT/intelligence}"
export MERIDIAN_WORKSPACE_PORT="${MERIDIAN_WORKSPACE_PORT:-18901}"
export MERIDIAN_GATEWAY_PORT="${MERIDIAN_GATEWAY_PORT:-8266}"

QUIET=0
if [[ "${1:-}" == "--no-summary" ]]; then
  QUIET=1
fi

RUNTIME_DIR="${MERIDIAN_ROOT}/runtime"
PID_DIR="${RUNTIME_DIR}/pids"
LOG_DIR="${RUNTIME_DIR}/logs"
mkdir -p "${PID_DIR}" "${LOG_DIR}"

resolve_org_id() {
  python3 - <<'PY'
import json
import os

kernel_root = os.environ["MERIDIAN_KERNEL_ROOT"]
path = os.path.join(kernel_root, "kernel", "organizations.json")
if not os.path.exists(path):
    print("local_foundry")
    raise SystemExit(0)

with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)
orgs = payload.get("organizations") or {}
for oid, org in orgs.items():
    if (org or {}).get("slug") == "meridian":
        print(oid)
        raise SystemExit(0)
print(next(iter(orgs.keys()), "local_foundry"))
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

export MERIDIAN_ORG_ID="${MERIDIAN_ORG_ID:-$(resolve_org_id)}"
export MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID:-$(resolve_workspace_org_id)}"

port_listening() {
  local port="$1"
  if command -v rg >/dev/null 2>&1; then
    ss -lnt "( sport = :${port} )" 2>/dev/null | rg -q ":${port}\\b"
  else
    ss -lnt "( sport = :${port} )" 2>/dev/null | grep -Eq ":${port}([^0-9]|$)"
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

start_workspace_if_needed() {
  if port_listening "$MERIDIAN_WORKSPACE_PORT"; then
    echo "[dev-up] workspace already listening on :${MERIDIAN_WORKSPACE_PORT}"
    return
  fi

  echo "[dev-up] starting workspace on :${MERIDIAN_WORKSPACE_PORT}"
  (
    cd "${MERIDIAN_INTELLIGENCE_ROOT}/company/meridian_platform"
    local org_args=()
    if [[ -n "${MERIDIAN_WORKSPACE_ORG_ID}" ]]; then
      org_args=(--org-id "${MERIDIAN_WORKSPACE_ORG_ID}")
    fi
    MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" \
    MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID}" \
    nohup python3 workspace.py --port "${MERIDIAN_WORKSPACE_PORT}" "${org_args[@]}" \
      >"${LOG_DIR}/workspace.log" 2>&1 &
    echo $! > "${PID_DIR}/workspace.pid"
  )
}

start_gateway_if_needed() {
  if port_listening "$MERIDIAN_GATEWAY_PORT"; then
    echo "[dev-up] gateway already listening on :${MERIDIAN_GATEWAY_PORT}"
    return
  fi

  echo "[dev-up] starting gateway on :${MERIDIAN_GATEWAY_PORT}"
  (
    cd "${MERIDIAN_INTELLIGENCE_ROOT}"
    MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" \
    MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID}" \
    MERIDIAN_WORKSPACE_API_BASE="http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}" \
    nohup python3 meridian_gateway.py >"${LOG_DIR}/gateway.log" 2>&1 &
    echo $! > "${PID_DIR}/gateway.pid"
  )
}

start_workspace_if_needed
wait_for_json "http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}/api/status" 35 >/dev/null

start_gateway_if_needed
STATUS_JSON="$(wait_for_json "http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}/api/status" 35)"
TEMPLATE_JSON="$(wait_for_json "http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}/api/institution/template" 35)"
TREASURY_JSON="$(wait_for_json "http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}/api/treasury" 35)"
export STATUS_JSON TEMPLATE_JSON TREASURY_JSON

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
