#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
export MERIDIAN_LOOM_ROOT="${MERIDIAN_LOOM_ROOT:-$MERIDIAN_ROOT/loom}"
export MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT:-$MERIDIAN_ROOT/kernel}"
export MERIDIAN_INTELLIGENCE_ROOT="${MERIDIAN_INTELLIGENCE_ROOT:-$MERIDIAN_ROOT/intelligence}"
export MERIDIAN_ORG_ID="${MERIDIAN_ORG_ID:-local_foundry}"
export LOOM_RUNTIME_ROOT="${LOOM_RUNTIME_ROOT:-$MERIDIAN_ROOT/runtime/default}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing required command: $cmd" >&2
    exit 1
  fi
}

require_cmd python3
require_cmd cargo

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

run_smoke_check() {
  if [ "${MERIDIAN_SKIP_SMOKE_CHECK:-0}" = "1" ]; then
    echo "[bootstrap] Skipping smoke check (MERIDIAN_SKIP_SMOKE_CHECK=1)"
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

echo "[bootstrap] Meridian root: $MERIDIAN_ROOT"
echo "[bootstrap] Initializing kernel state..."
(
  cd "$MERIDIAN_KERNEL_ROOT"
  python3 quickstart.py --init-only
)

RESOLVED_KERNEL_ORG_ID="$(resolve_kernel_org_id)"
if [ -n "$RESOLVED_KERNEL_ORG_ID" ]; then
  export MERIDIAN_ORG_ID="$RESOLVED_KERNEL_ORG_ID"
fi
echo "[bootstrap] Kernel org id: $MERIDIAN_ORG_ID"

echo "[bootstrap] Building Loom CLI..."
(
  cd "$MERIDIAN_LOOM_ROOT"
  cargo build -p meridian-loom --release
)

mkdir -p "$LOOM_RUNTIME_ROOT"
run_smoke_check

echo "[bootstrap] Bootstrap complete."
echo
echo "Next steps:"
echo "1) export MERIDIAN_ROOT=\"$MERIDIAN_ROOT\""
echo "2) export MERIDIAN_ORG_ID=\"$MERIDIAN_ORG_ID\""
echo "3) Run gateway: cd \"$MERIDIAN_INTELLIGENCE_ROOT\" && python3 meridian_gateway.py"
echo "4) Loom binary: \"$MERIDIAN_LOOM_ROOT/target/release/loom\""
