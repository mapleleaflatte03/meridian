#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/loom-observe-stream.XXXXXX")"
KERNEL_PATH="$(mktemp -d "${TMPDIR:-/tmp}/loom-observe-kernel.XXXXXX")"

cleanup() {
  rm -rf "${RUNTIME_ROOT}" "${KERNEL_PATH}"
}
trap cleanup EXIT

echo "[loom-acceptance] build loom binary"
(cd "${REPO_ROOT}" && cargo build -q -p meridian-loom)

echo "[loom-acceptance] scaffold kernel fixture"
mkdir -p "${KERNEL_PATH}/kernel"
cat > "${KERNEL_PATH}/kernel/runtimes.json" <<'JSON'
{
  "runtimes": {
    "local_kernel": {
      "id": "local_kernel",
      "label": "Local Kernel Runtime"
    },
    "loom_native": {
      "status": "official",
      "notes": "observe stream acceptance",
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
cat > "${KERNEL_PATH}/kernel/agent_registry.py" <<'PY'
import json, sys
agent_id = sys.argv[sys.argv.index('--agent_id') + 1]
org_id = sys.argv[sys.argv.index('--org_id') + 1] if '--org_id' in sys.argv else 'org_demo'
print(json.dumps({
  'id': agent_id,
  'name': agent_id.title(),
  'org_id': org_id,
  'role': 'operator',
  'economy_key': 'main',
  'approval_required': False,
  'budget': {'max_per_run_usd': 2.0},
  'runtime_binding': {
    'runtime_id': 'loom_native',
    'runtime_label': 'Loom Native Runtime',
    'bound_org_id': org_id,
    'boundary_name': 'workspace',
    'identity_model': 'session',
    'runtime_registered': True,
    'registration_status': 'registered'
  }
}, indent=2))
PY
cat > "${KERNEL_PATH}/kernel/court.py" <<'PY'
def get_restrictions(agent_id, org_id=None):
    return []
PY
cat > "${KERNEL_PATH}/kernel/authority.py" <<'PY'
def check_authority(agent_id, action, org_id=None):
    return True, "ok"
PY
cat > "${KERNEL_PATH}/kernel/treasury.py" <<'PY'
def check_budget(agent_id, estimated_cost, org_id=None):
    return True, "ok"
PY

echo "[loom-acceptance] init runtime root"
"${REPO_ROOT}/target/debug/loom" init \
  --mode embedded \
  --root "${RUNTIME_ROOT}" \
  --kernel-path "${KERNEL_PATH}" \
  --org-id "org_demo" >/dev/null

echo "[loom-acceptance] run observe watch stream"
WATCH_OUTPUT="$("${REPO_ROOT}/target/debug/loom" observe watch \
  --root "${RUNTIME_ROOT}" \
  --format json \
  --stream \
  --iterations 3 \
  --interval-seconds 0 \
  --fix-hints)"

python3 - <<'PY' "${WATCH_OUTPUT}" "${RUNTIME_ROOT}"
import json
import pathlib
import sys

output = sys.argv[1]
root = pathlib.Path(sys.argv[2])
lines = [line for line in output.splitlines() if line.strip()]
if len(lines) != 4:
    raise SystemExit(f"expected 4 output lines (3 frames + completion), got {len(lines)}")

for idx, line in enumerate(lines[:3], start=1):
    payload = json.loads(line)
    if payload.get("status") != "observe_watch_frame":
        raise SystemExit(f"frame {idx} status mismatch: {payload.get('status')}")
    if payload.get("iteration") != idx:
        raise SystemExit(f"frame {idx} iteration mismatch: {payload.get('iteration')}")
    if payload.get("alert_count", 0) < 1:
        raise SystemExit(f"frame {idx} expected alert_count >= 1")
    if not isinstance(payload.get("alerts"), list):
        raise SystemExit(f"frame {idx} alerts missing")

completion = json.loads(lines[-1])
if completion.get("status") != "observe_watch_complete":
    raise SystemExit(f"completion status mismatch: {completion.get('status')}")
if completion.get("emitted_frames") != 3:
    raise SystemExit(f"expected emitted_frames=3, got {completion.get('emitted_frames')}")

stream_path = root / "state/observability/alerts_stream.jsonl"
if not stream_path.exists():
    raise SystemExit(f"missing stream artifact: {stream_path}")

stream_lines = [line for line in stream_path.read_text().splitlines() if line.strip()]
if len(stream_lines) != 3:
    raise SystemExit(f"expected 3 stream lines, got {len(stream_lines)}")

for idx, line in enumerate(stream_lines, start=1):
    payload = json.loads(line)
    if payload.get("status") != "observe_watch_frame":
        raise SystemExit(f"stream line {idx} status mismatch: {payload.get('status')}")

print("stream_ok")
PY

echo "[loom-acceptance] PASS observe stream lane"
