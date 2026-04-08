#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${MERIDIAN_BASE_URL:-http://127.0.0.1:8266}"
OUT_DIR="${MERIDIAN_RESEARCH_OUT_DIR:-$ROOT_DIR/runtime/research}"
CASE_NAME="${1:-sanction_remediation_loop}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PREFIX="$OUT_DIR/${CASE_NAME}_${STAMP}"

mkdir -p "$OUT_DIR"

capture() {
  local suffix="$1"
  local path="$2"
  curl -fsS "$BASE_URL$path" > "${PREFIX}.${suffix}.json"
}

capture status_before /api/status
capture runtime_proof_before /api/runtime-proof
capture kernel_bundle_before /api/kernel-proof-bundle
capture treasury_before /api/treasury

if [ "${MERIDIAN_CASE_SLEEP_SECONDS:-0}" != "0" ]; then
  sleep "${MERIDIAN_CASE_SLEEP_SECONDS}"
fi

capture status_after /api/status
capture runtime_proof_after /api/runtime-proof
capture kernel_bundle_after /api/kernel-proof-bundle
capture treasury_after /api/treasury

python3 - "$PREFIX" <<'PY'
import json
import sys
from pathlib import Path

prefix = Path(sys.argv[1])

def load(name: str):
    return json.loads((prefix.parent / f"{prefix.name}.{name}.json").read_text(encoding="utf-8"))

status_before = load("status_before")
status_after = load("status_after")
proof_before = load("runtime_proof_before")
proof_after = load("runtime_proof_after")
bundle_before = load("kernel_bundle_before")
bundle_after = load("kernel_bundle_after")
treasury_before = load("treasury_before")
treasury_after = load("treasury_after")

summary = {
    "case_prefix": str(prefix),
    "before": {
        "runtime_id": status_before.get("runtime_id"),
        "slo_status": (status_before.get("slo") or {}).get("status"),
        "proof_mode": proof_before.get("proof_mode"),
        "kernel_bundle_status": bundle_before.get("status"),
        "treasury_balance_usd": treasury_before.get("balance_usd"),
    },
    "after": {
        "runtime_id": status_after.get("runtime_id"),
        "slo_status": (status_after.get("slo") or {}).get("status"),
        "proof_mode": proof_after.get("proof_mode"),
        "kernel_bundle_status": bundle_after.get("status"),
        "treasury_balance_usd": treasury_after.get("balance_usd"),
    },
    "invariants": {
        "runtime_id_stable": status_before.get("runtime_id") == status_after.get("runtime_id"),
        "proof_mode_stable": proof_before.get("proof_mode") == proof_after.get("proof_mode"),
        "kernel_bundle_route_present": bool(proof_after.get("kernel_bundle_route")),
    },
}

summary_path = prefix.parent / f"{prefix.name}.summary.json"
summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(summary_path)
PY

echo "[research-case] captured -> ${PREFIX}.*.json"
echo "[research-case] summary -> ${PREFIX}.summary.json"
