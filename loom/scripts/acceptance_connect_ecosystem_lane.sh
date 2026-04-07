#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TMP_DIR="$(mktemp -d /tmp/loom_connect_ecosystem_lane.XXXXXX)"
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
      "notes": "connect acceptance lane",
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

echo "[loom-acceptance] build loom binary"
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

echo "[loom-acceptance] init runtime root"
run_loom init --mode embedded --root "${ROOT_DIR}" --kernel-path "${KERNEL_DIR}" --org-id org_demo >/dev/null

declare -a ADAPTERS=(
  "telegram_adapter telegram"
  "discord_adapter discord"
  "browser_adapter browser"
  "shell_adapter shell"
  "desktop_adapter desktop"
  "webhook_adapter webhook"
)

echo "[loom-acceptance] scaffold + validate + enable + test + health for all transports"
for pair in "${ADAPTERS[@]}"; do
  name="${pair%% *}"
  transport="${pair##* }"
  adapter_id="${name//_/-}"

  run_loom_json connect scaffold --name "${name}" --transport "${transport}" --action-schema meridian.runtime.v1 --root "${ROOT_DIR}" >/dev/null
  run_loom_json connect validate --adapter-id "${adapter_id}" --root "${ROOT_DIR}" >/dev/null
  run_loom_json connect enable --adapter-id "${adapter_id}" --root "${ROOT_DIR}" >/dev/null
  run_loom_json connect test --adapter-id "${adapter_id}" --root "${ROOT_DIR}" >/dev/null
  run_loom_json connect health --adapter-id "${adapter_id}" --root "${ROOT_DIR}" >/dev/null
  run_loom_json connect diagnostics --adapter-id "${adapter_id}" --limit 5 --root "${ROOT_DIR}" >/dev/null
done

echo "[loom-acceptance] assert disabled adapter test fail path"
run_loom_json connect disable --adapter-id telegram-adapter --root "${ROOT_DIR}" >/dev/null
set +e
FAIL_OUTPUT="$(run_loom_json connect test --adapter-id telegram-adapter --root "${ROOT_DIR}" 2>&1)"
FAIL_STATUS=$?
set -e
if [[ ${FAIL_STATUS} -eq 0 ]]; then
  echo "expected connect test fail path for disabled adapter, but command succeeded" >&2
  exit 1
fi
if [[ "${FAIL_OUTPUT}" != *"adapter_disabled"* ]]; then
  echo "expected adapter_disabled fail reason, got:" >&2
  echo "${FAIL_OUTPUT}" >&2
  exit 1
fi

echo "[loom-acceptance] verify diagnostics + artifacts persisted"
python3 - <<'PY' "${ROOT_DIR}"
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
adapters = ["telegram-adapter", "discord-adapter", "browser-adapter", "shell-adapter", "desktop-adapter", "webhook-adapter"]
for adapter in adapters:
    health_path = root / "state/connect/health" / f"{adapter}.json"
    tests_path = root / "state/connect/tests" / f"{adapter}.jsonl"
    lifecycle_path = root / "state/connect/lifecycle" / f"{adapter}.jsonl"
    if not health_path.exists():
        raise SystemExit(f"missing health artifact: {health_path}")
    if not tests_path.exists():
        raise SystemExit(f"missing tests history: {tests_path}")
    if not tests_path.read_text().strip():
        raise SystemExit(f"empty tests history: {tests_path}")
    if not lifecycle_path.exists():
        raise SystemExit(f"missing lifecycle history: {lifecycle_path}")
    if not lifecycle_path.read_text().strip():
        raise SystemExit(f"empty lifecycle history: {lifecycle_path}")
    health = json.loads(health_path.read_text())
    if "lifecycle_state" not in health:
        raise SystemExit(f"missing lifecycle_state in health snapshot: {health_path}")

latest_path = root / "artifacts/connect/latest.json"
if not latest_path.exists():
    raise SystemExit(f"missing latest artifact: {latest_path}")
latest = json.loads(latest_path.read_text())
if latest.get("status") not in {"connect_tested", "connect_health", "connect_diagnostics", "connect_disabled", "connect_enabled", "connect_validated", "connect_scaffolded"}:
    raise SystemExit(f"unexpected latest status: {latest.get('status')}")
print("artifacts_ok")
PY

echo "[loom-acceptance] verify adapter diagnostics query surface"
DIAGNOSTICS_JSON="$(run_loom_json connect diagnostics --adapter-id telegram-adapter --limit 5 --root "${ROOT_DIR}")"
python3 - <<'PY' "${DIAGNOSTICS_JSON}"
import json
import sys
payload = json.loads(sys.argv[1])
if payload.get("status") != "connect_diagnostics":
    raise SystemExit(f"unexpected diagnostics status: {payload.get('status')}")
if payload.get("adapter_id") != "telegram-adapter":
    raise SystemExit(f"unexpected diagnostics adapter_id: {payload.get('adapter_id')}")
if payload.get("tests_recent_count", 0) < 1:
    raise SystemExit("expected tests_recent_count >= 1")
if payload.get("lifecycle_recent_count", 0) < 1:
    raise SystemExit("expected lifecycle_recent_count >= 1")
if "health_snapshot" not in payload:
    raise SystemExit("expected health_snapshot field")
PY

echo "[loom-acceptance] verify reconnect->fallback lifecycle semantics"
python3 - <<'PY' "${ROOT_DIR}"
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
registry_path = root / "state/connect/registry.json"
registry = json.loads(registry_path.read_text())
for adapter in registry.get("adapters", []):
    if adapter.get("adapter_id") == "discord-adapter":
        adapter["action_schema"] = ""
registry_path.write_text(json.dumps(registry, indent=2) + "\n")
PY

set +e
DISCORD_FAIL="$(run_loom_json connect test --adapter-id discord-adapter --root "${ROOT_DIR}" 2>&1)"
DISCORD_FAIL_STATUS=$?
set -e
if [[ ${DISCORD_FAIL_STATUS} -eq 0 ]]; then
  echo "expected connect test fail for discord-adapter degraded action schema, but command succeeded" >&2
  exit 1
fi
if [[ "${DISCORD_FAIL}" != *"missing_action_schema"* ]]; then
  echo "expected missing_action_schema fail reason, got:" >&2
  echo "${DISCORD_FAIL}" >&2
  exit 1
fi

for _ in 1 2 3; do
  HEALTH_JSON="$(run_loom_json connect health --adapter-id discord-adapter --root "${ROOT_DIR}")"
  python3 - <<'PY' "${HEALTH_JSON}"
import json
import sys
payload = json.loads(sys.argv[1])
if payload.get("lifecycle_state") != "reconnecting":
    raise SystemExit(f"expected reconnecting, got {payload.get('lifecycle_state')}")
if payload.get("recommended_action") != "reconnect":
    raise SystemExit(f"expected reconnect action, got {payload.get('recommended_action')}")
PY
done

FINAL_HEALTH="$(run_loom_json connect health --adapter-id discord-adapter --root "${ROOT_DIR}")"
python3 - <<'PY' "${FINAL_HEALTH}"
import json
import sys
payload = json.loads(sys.argv[1])
if payload.get("lifecycle_state") != "fallback":
    raise SystemExit(f"expected fallback, got {payload.get('lifecycle_state')}")
if payload.get("recommended_action") != "shadow_or_local_queue":
    raise SystemExit(f"expected shadow_or_local_queue action, got {payload.get('recommended_action')}")
PY

SCORECARD_FIX_JSON="$(run_loom_json connect scorecard --fix --root "${ROOT_DIR}")"
python3 - <<'PY' "${SCORECARD_FIX_JSON}"
import json
import sys
payload = json.loads(sys.argv[1])
if payload.get("status") != "connect_scorecard":
    raise SystemExit(f"unexpected scorecard status: {payload.get('status')}")
if payload.get("fix_requested") is not True:
    raise SystemExit("expected fix_requested=true")
if payload.get("remediations_applied", 0) < 1:
    raise SystemExit("expected remediations_applied >= 1")
PY

echo "[loom-acceptance] verify metrics window and retention prune"
python3 - <<'PY' "${ROOT_DIR}"
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
tests_path = root / "state/connect/tests/telegram-adapter.jsonl"
lifecycle_path = root / "state/connect/lifecycle/telegram-adapter.jsonl"

tests_path.write_text(
    '{"schema_version":"meridian.connect.test_event.v1","adapter_id":"telegram-adapter","test_status":"pass","test_reason":"stale","tested_at":"1"}\n'
    '{"schema_version":"meridian.connect.test_event.v1","adapter_id":"telegram-adapter","test_status":"pass","test_reason":"fresh","tested_at":"9999999999"}\n'
)
lifecycle_path.write_text(
    '{"schema_version":"meridian.connect.lifecycle_event.v1","adapter_id":"telegram-adapter","state":"fallback","action":"health_fallback","reason":"stale","recorded_at":"1"}\n'
    '{"schema_version":"meridian.connect.lifecycle_event.v1","adapter_id":"telegram-adapter","state":"fallback","action":"health_fallback","reason":"fresh","recorded_at":"9999999998"}\n'
    '{"schema_version":"meridian.connect.lifecycle_event.v1","adapter_id":"telegram-adapter","state":"ready","action":"health_ready","reason":"fresh","recorded_at":"9999999999"}\n'
)
PY

METRICS_JSON="$(run_loom_json connect metrics --adapter-id telegram-adapter --root "${ROOT_DIR}")"
python3 - <<'PY' "${METRICS_JSON}"
import json
import sys
payload = json.loads(sys.argv[1])
if payload.get("status") != "connect_metrics":
    raise SystemExit(f"unexpected status: {payload.get('status')}")
if payload.get("tests_total", 0) < 1:
    raise SystemExit("expected tests_total >= 1")
if payload.get("fallback_events", 0) < 1:
    raise SystemExit("expected fallback_events >= 1")
PY

PRUNE_JSON="$(run_loom_json connect prune --adapter-id telegram-adapter --root "${ROOT_DIR}")"
python3 - <<'PY' "${PRUNE_JSON}" "${ROOT_DIR}"
import json
import pathlib
import sys

payload = json.loads(sys.argv[1])
root = pathlib.Path(sys.argv[2])
if payload.get("status") != "connect_pruned":
    raise SystemExit(f"unexpected prune status: {payload.get('status')}")
if payload.get("removed_tests_entries") != 1:
    raise SystemExit(f"expected removed_tests_entries=1, got {payload.get('removed_tests_entries')}")
if payload.get("removed_lifecycle_entries") != 1:
    raise SystemExit(f"expected removed_lifecycle_entries=1, got {payload.get('removed_lifecycle_entries')}")

tests_after = (root / "state/connect/tests/telegram-adapter.jsonl").read_text()
if '"reason":"stale"' in tests_after:
    raise SystemExit("stale tests entry should be pruned")
if not tests_after.strip():
    raise SystemExit("tests history should keep non-stale entries")
lifecycle_after = (root / "state/connect/lifecycle/telegram-adapter.jsonl").read_text()
if '"reason":"stale"' in lifecycle_after:
    raise SystemExit("stale lifecycle entry should be pruned")
if not lifecycle_after.strip():
    raise SystemExit("lifecycle history should keep non-stale entries")
PY

SCORECARD_JSON="$(run_loom_json connect scorecard --root "${ROOT_DIR}")"
python3 - <<'PY' "${SCORECARD_JSON}"
import json
import sys
payload = json.loads(sys.argv[1])
if payload.get("status") != "connect_scorecard":
    raise SystemExit(f"unexpected scorecard status: {payload.get('status')}")
if payload.get("total_adapters", 0) < 6:
    raise SystemExit(f"expected total_adapters >= 6, got {payload.get('total_adapters')}")
if payload.get("overall_status") not in {"healthy", "degraded"}:
    raise SystemExit(f"unexpected overall_status: {payload.get('overall_status')}")
rows = payload.get("adapters") or []
if len(rows) < 6:
    raise SystemExit(f"expected at least 6 scorecard rows, got {len(rows)}")
for row in rows:
    if row.get("security_posture_ok") is not True:
        raise SystemExit(f"expected security_posture_ok=true for {row.get('adapter_id')}")
PY

echo "[loom-acceptance] PASS connect ecosystem lane"
