#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
export MERIDIAN_LOOM_ROOT="${MERIDIAN_LOOM_ROOT:-$MERIDIAN_ROOT/loom}"
export MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT:-$MERIDIAN_ROOT/kernel}"
export MERIDIAN_INTELLIGENCE_ROOT="${MERIDIAN_INTELLIGENCE_ROOT:-$MERIDIAN_ROOT/intelligence}"
export MERIDIAN_INSTALL_MODE="${MERIDIAN_INSTALL_MODE:-user}"
export MERIDIAN_ORG_ID="${MERIDIAN_ORG_ID:-}"
export LOOM_RUNTIME_ROOT="${LOOM_RUNTIME_ROOT:-$MERIDIAN_ROOT/runtime/default}"
export MERIDIAN_WORKSPACE_CREDENTIALS_FILE="${MERIDIAN_WORKSPACE_CREDENTIALS_FILE:-$MERIDIAN_ROOT/runtime/workspace_credentials}"
if [ -z "${MERIDIAN_AUTO_START_STACK:-}" ]; then
  if [ "${MERIDIAN_INSTALL_MODE}" = "user" ]; then
    export MERIDIAN_AUTO_START_STACK="0"
  else
    export MERIDIAN_AUTO_START_STACK="1"
  fi
else
  export MERIDIAN_AUTO_START_STACK
fi
export MERIDIAN_GATEWAY_PORT="${MERIDIAN_GATEWAY_PORT:-8266}"
export MERIDIAN_HEARTBEAT_ENABLED="${MERIDIAN_HEARTBEAT_ENABLED:-0}"
export MERIDIAN_ENV_PROFILE="${MERIDIAN_ENV_PROFILE:-local}"

case "${MERIDIAN_INSTALL_MODE}" in
  user|demo|maintainer)
    ;;
  *)
    echo "[bootstrap] Unsupported MERIDIAN_INSTALL_MODE=${MERIDIAN_INSTALL_MODE}. Use user, demo, or maintainer." >&2
    exit 1
    ;;
esac

if [[ "${MERIDIAN_ENV_PROFILE}" != "local" && "${MERIDIAN_WORKSPACE_PASSWORD:-}" == "meridian_local_operator" ]]; then
  echo "[ERROR] MERIDIAN_WORKSPACE_PASSWORD must not use local default when MERIDIAN_ENV_PROFILE=${MERIDIAN_ENV_PROFILE}" >&2
  exit 1
fi

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing required command: $cmd" >&2
    exit 1
  fi
}

require_cmd python3
require_cmd curl

ensure_workspace_credentials() {
  MERIDIAN_INTELLIGENCE_ROOT="${MERIDIAN_INTELLIGENCE_ROOT}" \
  MERIDIAN_WORKSPACE_CREDENTIALS_FILE="${MERIDIAN_WORKSPACE_CREDENTIALS_FILE}" \
  MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID:-}" \
  MERIDIAN_WORKSPACE_PASSWORD="${MERIDIAN_WORKSPACE_PASSWORD:-meridian_local_operator}" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

org_file = Path(os.environ["MERIDIAN_INTELLIGENCE_ROOT"]) / "company" / "meridian_platform" / "organizations.json"
cred_file = Path(os.environ["MERIDIAN_WORKSPACE_CREDENTIALS_FILE"])
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
    raise SystemExit("workspace credentials require an institution created through onboarding or an explicit MERIDIAN_WORKSPACE_ORG_ID")

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

resolve_kernel_org_id() {
  python3 - <<'PY'
import json
import os
import sys

kernel_root = os.environ.get("MERIDIAN_KERNEL_ROOT", "")
path = os.path.join(kernel_root, "kernel", "organizations.json")
if not os.path.exists(path):
    print("")
    sys.exit(0)

with open(path, "r", encoding="utf-8") as f:
    payload = json.load(f)

orgs = payload.get("organizations") or {}
selected = ""
for org_id, org in orgs.items():
    if (org or {}).get("slug") == "meridian":
        selected = org_id
        break

if not selected and orgs:
    selected = next(iter(orgs.keys()))

print(selected)
PY
}

seed_workspace_founding_org() {
  python3 - <<'PY'
import os
import sys

platform_dir = os.path.join(
    os.environ["MERIDIAN_INTELLIGENCE_ROOT"],
    "company",
    "meridian_platform",
)
sys.path.insert(0, platform_dir)

from organizations import (  # noqa: E402
    DEFAULT_POLICY_DEFAULTS,
    create_org,
    load_orgs,
    save_orgs,
)

orgs = load_orgs()
organizations = orgs.setdefault("organizations", {})
founding_org_id = ""
for oid, org in organizations.items():
    if (org or {}).get("slug") == "meridian":
        founding_org_id = oid
        break

if not founding_org_id:
    founding_org_id = create_org(
        name="Meridian",
        owner_id="user_meridian_5322393870",
        plan="enterprise",
    )
    orgs = load_orgs()
    organizations = orgs.setdefault("organizations", {})

org = organizations.get(founding_org_id) or {}
changed = False
if org.get("slug") != "meridian":
    org["slug"] = "meridian"
    changed = True
if "charter" not in org:
    org["charter"] = ""
    changed = True

policy_defaults = dict(DEFAULT_POLICY_DEFAULTS)
policy_defaults.update(dict(org.get("policy_defaults") or {}))
if org.get("policy_defaults") != policy_defaults:
    org["policy_defaults"] = policy_defaults
    changed = True

expected_treasury = f"capsule://{founding_org_id}/treasury"
if org.get("treasury_id") != expected_treasury:
    org["treasury_id"] = expected_treasury
    changed = True

if org.get("lifecycle_state") not in {"founding", "active", "suspended", "dissolved"}:
    org["lifecycle_state"] = "active"
    changed = True
if "settings" not in org:
    org["settings"] = {}
    changed = True

if changed:
    organizations[founding_org_id] = org
    save_orgs(orgs)

print(founding_org_id)
PY
}

run_workspace_platform_bootstrap() {
  (
    cd "${MERIDIAN_INTELLIGENCE_ROOT}/company/meridian_platform"
    MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT}" python3 bootstrap.py >/tmp/meridian_platform_bootstrap.log
  )
}

ensure_intelligence_gateway_config() {
  (
    cd "${MERIDIAN_INTELLIGENCE_ROOT}"
    python3 - <<'PY'
from meridian_config import load_config, save_config
save_config(load_config(required=False))
PY
  )
}

run_kernel_smoke_check() {
  if [ "${MERIDIAN_SKIP_SMOKE_CHECK:-0}" = "1" ]; then
    echo "[bootstrap] Skipping kernel smoke check (MERIDIAN_SKIP_SMOKE_CHECK=1)"
    return
  fi

  echo "[bootstrap] Running kernel + governance smoke check..."
  (
    cd "$MERIDIAN_KERNEL_ROOT"
    MERIDIAN_ORG_ID="$MERIDIAN_ORG_ID" python3 - <<'PY'
import json
import os
import sys

kernel_root = os.getcwd()
sys.path.insert(0, kernel_root)
sys.path.insert(0, os.path.join(kernel_root, "kernel"))

from kernel.organizations import load_orgs, DEFAULT_POLICY_DEFAULTS
from kernel.court import _load_records as load_court_records

orgs = (load_orgs() or {}).get("organizations") or {}
if not orgs:
    raise SystemExit("smoke-check failed: no institutions found in kernel state")

requested_org_id = os.environ.get("MERIDIAN_ORG_ID", "").strip()
org_id = requested_org_id if requested_org_id in orgs else ""
if not org_id:
    for oid, org in orgs.items():
        if (org or {}).get("slug") == "meridian":
            org_id = oid
            break
if not org_id:
    org_id = next(iter(orgs.keys()))

org = orgs[org_id]
policy_defaults = dict(DEFAULT_POLICY_DEFAULTS)
policy_defaults.update(dict(org.get("policy_defaults") or {}))
for key in ("max_budget_per_agent_usd", "require_approval_above_usd", "auto_sanctions_enabled"):
    if key not in policy_defaults:
        raise SystemExit(f"smoke-check failed: policy_defaults missing '{key}'")

ledger_path = os.path.join(kernel_root, "economy", "ledger.json")
with open(ledger_path, "r", encoding="utf-8") as f:
    ledger = json.load(f)
treasury = dict(ledger.get("treasury") or {})
if "cash_usd" not in treasury or "reserve_floor_usd" not in treasury:
    raise SystemExit("smoke-check failed: treasury baseline keys missing in economy/ledger.json")

records = load_court_records(org_id=org_id)
if not isinstance(records, dict) or "violations" not in records or "appeals" not in records:
    raise SystemExit("smoke-check failed: court records are not initialized")

institution_template = {
    "org_id": org_id,
    "institution_name": org.get("name", ""),
    "charter_template": org.get("charter", ""),
    "policy_defaults": policy_defaults,
    "court_rule_set": [
        "budget_overspend_guard",
        "proof_integrity_guard",
        "authority_breach_guard",
    ],
    "rollback_contract": "capsule_snapshot_restore",
}

print(json.dumps({
    "status": "ok",
    "org_id": org_id,
    "institution_name": org.get("name", ""),
    "institution_template_ready": bool(institution_template.get("charter_template") is not None),
    "court_rules": len(institution_template["court_rule_set"]),
    "treasury_balance_usd": treasury.get("cash_usd"),
    "treasury_reserve_floor_usd": treasury.get("reserve_floor_usd"),
    "court_open_violations": len(records.get("violations", {})),
    "court_pending_appeals": len(records.get("appeals", {})),
}))
PY
  )
}

run_gateway_smoke_check() {
  if [ "${MERIDIAN_SKIP_GATEWAY_SMOKE_CHECK:-0}" = "1" ]; then
    echo "[bootstrap] Skipping gateway smoke check (MERIDIAN_SKIP_GATEWAY_SMOKE_CHECK=1)"
    return
  fi

  local base_url="http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}"
  local report_path="${MERIDIAN_ROOT}/runtime/bootstrap_gateway_smoke.json"
  echo "[bootstrap] Running gateway smoke check via ${base_url}..."
  BASE_URL="${base_url}" REPORT_PATH="${report_path}" python3 - <<'PY'
import json
import os
import time
import urllib.request

base = os.environ["BASE_URL"].rstrip("/")
report_path = os.environ["REPORT_PATH"]

def fetch(path: str, timeout: float = 4.0):
    with urllib.request.urlopen(base + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def parse_court_counters(status_payload: dict):
    court = status_payload.get("court") or {}
    open_violations_raw = court.get("open_violations")
    pending_appeals_raw = court.get("pending_appeals")

    if isinstance(open_violations_raw, list):
        open_violations_count = len(open_violations_raw)
    elif isinstance(open_violations_raw, int):
        open_violations_count = open_violations_raw
    else:
        return None

    if isinstance(pending_appeals_raw, list):
        pending_appeals_count = len(pending_appeals_raw)
    elif isinstance(pending_appeals_raw, int):
        pending_appeals_count = pending_appeals_raw
    else:
        return None

    return int(open_violations_count), int(pending_appeals_count)

deadline = time.time() + 60
status = None
open_violations_count = None
pending_appeals_count = None
last_error = None
while time.time() < deadline:
    try:
        candidate = fetch("/api/status", timeout=8.0)
        parsed = parse_court_counters(candidate)
        if parsed is None:
            last_error = "status snapshot missing court counters"
            time.sleep(0.5)
            continue
        status = candidate
        open_violations_count, pending_appeals_count = parsed
        break
    except Exception as exc:  # noqa: BLE001
        last_error = exc
        time.sleep(0.5)

if status is None or open_violations_count is None or pending_appeals_count is None:
    raise SystemExit(f"gateway smoke-check failed: {last_error}")

template = fetch("/api/institution/template")
treasury = fetch("/api/treasury")

if template.get("schema_version") != "meridian.institution_template.v1":
    raise SystemExit("gateway smoke-check failed: invalid institution template schema")
if len(template.get("court_rule_set") or []) < 3:
    raise SystemExit("gateway smoke-check failed: court_rule_set is not initialized")
if "balance_usd" not in treasury or "reserve_floor_usd" not in treasury:
    raise SystemExit("gateway smoke-check failed: treasury snapshot missing baseline keys")

report = {
    "status": "ok",
    "org_id": ((status.get("context") or {}).get("bound_org_id") or "").strip(),
    "runtime_id": status.get("runtime_id"),
    "slo_status": (status.get("slo") or {}).get("status"),
    "institution_template_schema": template.get("schema_version"),
    "court_rule_count": len(template.get("court_rule_set") or []),
    "treasury_balance_usd": treasury.get("balance_usd"),
    "treasury_reserve_floor_usd": treasury.get("reserve_floor_usd"),
    "court_open_violations": int(open_violations_count),
    "court_pending_appeals": int(pending_appeals_count),
}

os.makedirs(os.path.dirname(report_path), exist_ok=True)
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)
print(json.dumps(report))
PY
}

echo "[bootstrap] Meridian root: $MERIDIAN_ROOT"
echo "[bootstrap] Initializing kernel state..."
(
  cd "$MERIDIAN_KERNEL_ROOT"
  python3 quickstart.py --init-only
)

if [ "${MERIDIAN_INSTALL_MODE}" != "user" ]; then
  RESOLVED_KERNEL_ORG_ID="$(resolve_kernel_org_id)"
  if [ -n "$RESOLVED_KERNEL_ORG_ID" ]; then
    export MERIDIAN_ORG_ID="$RESOLVED_KERNEL_ORG_ID"
  fi
  echo "[bootstrap] Kernel org id: $MERIDIAN_ORG_ID"
else
  echo "[bootstrap] User mode: skipping kernel org resolution (clean-slate)."
fi

if [ "${MERIDIAN_INSTALL_MODE}" = "user" ]; then
  echo "[bootstrap] User mode: leaving workspace state clean-slate for onboarding."
  echo "[bootstrap] No institution seed, workspace credentials, or auto-started operator stack will be created."
else
  WORKSPACE_ORG_ID="$(seed_workspace_founding_org)"
  if [ -n "$WORKSPACE_ORG_ID" ]; then
    export MERIDIAN_WORKSPACE_ORG_ID="$WORKSPACE_ORG_ID"
  fi
  ensure_workspace_credentials >/dev/null
  echo "[bootstrap] Workspace org id: ${MERIDIAN_WORKSPACE_ORG_ID:-<auto>}"
  echo "[bootstrap] Bootstrapping workspace platform state..."
  run_workspace_platform_bootstrap
  echo "[bootstrap] Ensuring intelligence gateway config..."
  ensure_intelligence_gateway_config
fi

if [ "${MERIDIAN_SKIP_LOOM_BUILD:-0}" = "1" ]; then
  echo "[bootstrap] Skipping Loom build (MERIDIAN_SKIP_LOOM_BUILD=1)"
else
  require_cmd cargo
  echo "[bootstrap] Building Loom CLI..."
  (
    cd "$MERIDIAN_LOOM_ROOT"
    cargo build -p meridian-loom --release
  )
fi

mkdir -p "$LOOM_RUNTIME_ROOT"

if [ "${MERIDIAN_INSTALL_MODE}" = "user" ]; then
  echo "[bootstrap] User mode bootstrap complete after kernel/runtime preparation."
else
  run_kernel_smoke_check

  if [ "${MERIDIAN_AUTO_START_STACK}" = "1" ]; then
    echo "[bootstrap] Starting local workspace+gateway stack..."
    "${MERIDIAN_ROOT}/scripts/dev-up.sh" --no-summary
  else
    echo "[bootstrap] Auto-start disabled (MERIDIAN_AUTO_START_STACK=${MERIDIAN_AUTO_START_STACK})"
  fi

  run_gateway_smoke_check
fi

echo "[bootstrap] Bootstrap complete."
echo
if [ "${MERIDIAN_INSTALL_MODE}" = "user" ]; then
  echo "Next steps:"
  echo "1) Complete onboarding to create your first institution."
  echo "2) Start the local stack after onboarding: \"$MERIDIAN_ROOT/scripts/dev-up.sh\""
  echo "3) Stop the local stack when needed: \"$MERIDIAN_ROOT/scripts/dev-down.sh\""
  echo "4) Provision your first agent with explicit institution context:"
  echo "   MERIDIAN_ORG_ID=<your-org-id> \"$MERIDIAN_ROOT/scripts/new-first-agent.sh\" \"My Assistant\""
  echo "5) Loom binary: \"$MERIDIAN_LOOM_ROOT/target/release/loom\""
else
  echo "Next steps:"
  echo "1) export MERIDIAN_ROOT=\"$MERIDIAN_ROOT\""
  echo "2) export MERIDIAN_ORG_ID=\"$MERIDIAN_ORG_ID\""
  echo "3) Stack up: \"$MERIDIAN_ROOT/scripts/dev-up.sh\""
  echo "4) Stack down: \"$MERIDIAN_ROOT/scripts/dev-down.sh\""
  echo "5) Loom binary: \"$MERIDIAN_LOOM_ROOT/target/release/loom\""
  echo "6) Gateway smoke report: \"$MERIDIAN_ROOT/runtime/bootstrap_gateway_smoke.json\""
fi
