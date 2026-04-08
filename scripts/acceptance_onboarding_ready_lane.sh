#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "[onboarding-lane] bootstrap full stack (skip loom build for fast/portable gate)"
MERIDIAN_SKIP_LOOM_BUILD=1 \
MERIDIAN_AUTO_START_STACK=1 \
./scripts/bootstrap_full.sh >/tmp/meridian_onboarding_bootstrap.log

echo "[onboarding-lane] validate bootstrap smoke report"
python3 - <<'PY'
import json
from pathlib import Path

report_path = Path("runtime/bootstrap_gateway_smoke.json")
assert report_path.exists(), "missing runtime/bootstrap_gateway_smoke.json"
payload = json.loads(report_path.read_text(encoding="utf-8"))

assert payload.get("status") == "ok", payload
assert payload.get("institution_template_schema") == "meridian.institution_template.v1", payload
assert int(payload.get("court_rule_count") or 0) >= 3, payload
assert payload.get("treasury_balance_usd") is not None, payload
assert payload.get("treasury_reserve_floor_usd") is not None, payload
assert payload.get("runtime_id"), payload
PY

echo "[onboarding-lane] verify local API readiness contract"
python3 - <<'PY'
import json
import urllib.request

BASE = "http://127.0.0.1:8266"

def get_json(path: str):
    with urllib.request.urlopen(BASE + path, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

status = get_json("/api/status")
template = get_json("/api/institution/template")
treasury = get_json("/api/treasury")
runtime_proof = get_json("/api/runtime-proof")
kernel_bundle = get_json("/api/kernel-proof-bundle")

assert status.get("runtime_id"), status
slo = status.get("slo") or {}
assert slo.get("status") in {"healthy", "warning", "breach"}, status

status_blob = json.dumps(status).lower()
for banned in ("founder", "founding", "commercial", "checkout", "license"):
    assert banned not in status_blob, f"legacy wording '{banned}' found in /api/status"

assert template.get("schema_version") == "meridian.institution_template.v1", template
assert len(template.get("court_rule_set") or []) >= 3, template
assert isinstance(template.get("policy_defaults"), dict), template

assert treasury.get("balance_usd") is not None, treasury
assert treasury.get("reserve_floor_usd") is not None, treasury

assert runtime_proof.get("runtime_id"), runtime_proof
assert kernel_bundle.get("proof_bundle_version"), kernel_bundle
PY

echo "[onboarding-lane] PASS"
