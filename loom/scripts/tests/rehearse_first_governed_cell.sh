#!/usr/bin/env bash
set -euo pipefail

# Meridian Loom // First Governed Cell Rehearsal
#
# Runs the steps from docs/FIRST_GOVERNED_CELL.md automatically.
# Creates a fixture kernel, initializes a workspace, enqueues an action,
# runs the supervisor, and inspects the result.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOOM="${LOOM:-${REPO_ROOT}/target/release/loom}"
ROOT_DIR="${1:-/tmp/loom-first-cell}"
KERNEL_PATH="$(mktemp -d /tmp/loom-first-cell-kernel.XXXXXX)"
SOURCE_KERNEL="${SOURCE_KERNEL:-/tmp/meridian-kernel}"

cleanup() {
  rm -rf "${ROOT_DIR}" "${KERNEL_PATH}"
}
trap cleanup EXIT

echo "== Meridian Loom // First Governed Cell Rehearsal =="
echo "root:   ${ROOT_DIR}"
echo "kernel: ${KERNEL_PATH}"
echo "agent:  agent_tutorial"
echo "org:    org_tutorial"
echo ""

# ---- Build if needed ----
if [[ ! -x "${LOOM}" ]]; then
  echo "Binary not found at ${LOOM}, building..."
  (cd "${REPO_ROOT}" && cargo build --release --workspace)
fi

# ---- Fixture kernel setup ----
echo "--- Setting up fixture kernel ---"
rm -rf "${ROOT_DIR}"
mkdir -p "${KERNEL_PATH}/kernel/adapters"

cat > "${KERNEL_PATH}/kernel/runtimes.json" <<'EOF'
{
  "runtimes": {
    "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
    "loom_native": {
      "status": "experimental",
      "notes": "first governed cell tutorial",
      "contract_compliance": {
        "agent_identity": null,
        "action_envelope": null,
        "cost_attribution": null,
        "approval_hook": null,
        "audit_emission": null,
        "sanction_controls": null,
        "budget_gate": null
      }
    }
  }
}
EOF

cat > "${KERNEL_PATH}/kernel/agent_registry.py" <<'EOF'
import json
import sys

agent_id = sys.argv[sys.argv.index('--agent_id') + 1]
org_id = 'org_tutorial'
if '--org_id' in sys.argv:
    org_id = sys.argv[sys.argv.index('--org_id') + 1]

if agent_id in ('agent_tutorial', 'tutorial', 'Tutorial'):
    print(json.dumps({
        'id': 'agent_tutorial',
        'name': 'Tutorial Agent',
        'org_id': org_id,
        'role': 'analyst',
        'economy_key': 'tutorial',
        'approval_required': False,
        'restrictions': [],
        'sanction_decision': 'clear',
        'budget': {'max_per_run_usd': 5.0},
        'runtime_binding': {
            'runtime_id': 'local_kernel',
            'runtime_label': 'Local Kernel Runtime',
            'bound_org_id': org_id,
            'boundary_name': 'workspace',
            'identity_model': 'session',
            'runtime_registered': True,
            'registration_status': 'registered'
        }
    }, indent=2))
else:
    print(f'Not found: {agent_id}')
EOF

cat > "${KERNEL_PATH}/kernel/court.py" <<'EOF'
def get_restrictions(agent_id, org_id=None):
    return []
EOF

cat > "${KERNEL_PATH}/kernel/authority.py" <<'EOF'
def check_authority(agent_id, action, org_id=None):
    return True, 'ok'
EOF

cat > "${KERNEL_PATH}/kernel/treasury.py" <<'EOF'
def check_budget(agent_id, cost_usd, org_id=None):
    return True, 'ok'
def reserve_runtime_budget(agent_id, estimated_cost, org_id=None, action=None, resource=None, context=None, policy_ref=None):
    ih = context.get('input_hash','') if context else ''
    return {"allowed": True, "reservation_id": f"res_{agent_id}_{ih}", "reason": "fixture budget ok"}
def commit_runtime_budget(reservation_id, actual_cost=0.0, note=''):
    return {"status": "committed", "reservation_id": reservation_id, "actual_cost": actual_cost}
def release_runtime_budget(reservation_id, reason=''):
    return {"status": "released", "reservation_id": reservation_id}
EOF

# Copy audit.py from source kernel if available, otherwise create stub
if [[ -f "${SOURCE_KERNEL}/kernel/audit.py" ]]; then
  cp "${SOURCE_KERNEL}/kernel/audit.py" "${KERNEL_PATH}/kernel/audit.py"
else
  cat > "${KERNEL_PATH}/kernel/audit.py" <<'PYEOF'
import json, sys, pathlib, time
def log_runtime(event_type, payload, kernel_path=None):
    target = pathlib.Path(kernel_path or '.') / 'kernel' / 'runtime_audit' / 'loom_runtime_events.jsonl'
    target.parent.mkdir(parents=True, exist_ok=True)
    entry = {'ts': time.time(), 'event_type': event_type, **payload}
    with open(target, 'a') as f:
        f.write(json.dumps(entry) + '\n')
if __name__ == '__main__':
    if 'log-runtime' in sys.argv:
        idx = sys.argv.index('log-runtime')
        event_type = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else 'unknown'
        payload_str = sys.argv[idx + 2] if len(sys.argv) > idx + 2 else '{}'
        kernel_path = None
        if '--kernel-path' in sys.argv:
            kernel_path = sys.argv[sys.argv.index('--kernel-path') + 1]
        log_runtime(event_type, json.loads(payload_str), kernel_path=kernel_path)
PYEOF
fi

cat > "${KERNEL_PATH}/kernel/metering.py" <<'EOF'
def record(*args, **kwargs):
    return 'meter_fixture'
EOF

cat > "${KERNEL_PATH}/kernel/adapters/__init__.py" <<'EOF'
# fixture package
EOF

cat > "${KERNEL_PATH}/kernel/adapters/legacy_v1_compatible.py" <<'EOF'
from authority import check_authority
from court import get_restrictions
from treasury import check_budget

def pre_session_check(org_id, agent_id):
    restrictions = list(get_restrictions(agent_id, org_id=org_id) or [])
    if 'execute' in restrictions or 'remediation_only' in restrictions:
        return {'allowed': False, 'reason': f'Agent {agent_id} is restricted from execute', 'restrictions': restrictions}
    return {'allowed': True, 'reason': 'ok', 'restrictions': restrictions}

def pre_action_check(org_id, envelope):
    session_gate = pre_session_check(org_id, envelope['agent_id'])
    if not session_gate['allowed']:
        return {'allowed': False, 'reason': session_gate['reason'], 'stage': 'sanction_controls', 'envelope': envelope, 'restrictions': session_gate['restrictions']}
    allowed, reason = check_authority(envelope['agent_id'], envelope['action_type'], org_id=org_id)
    if not allowed:
        return {'allowed': False, 'reason': reason, 'stage': 'approval_hook', 'envelope': envelope, 'restrictions': session_gate['restrictions']}
    estimated_cost = envelope.get('estimated_cost_usd', 0.0)
    if estimated_cost > 0:
        allowed, reason = check_budget(envelope['agent_id'], estimated_cost, org_id=org_id)
        if not allowed:
            return {'allowed': False, 'reason': reason, 'stage': 'budget_gate', 'envelope': envelope, 'restrictions': session_gate['restrictions']}
    return {'allowed': True, 'reason': 'ok', 'stage': 'ok', 'envelope': envelope, 'restrictions': session_gate['restrictions']}
EOF

export MERIDIAN_LEGACY_V1_PROOF_SCRIPT="${KERNEL_PATH}/kernel/missing_legacy_v1_runtime_proof.py"

echo ""

# ---- Step 1: Initialize ----
echo "--- Step 1: Initialize workspace ---"
"${LOOM}" init \
  --mode embedded \
  --kernel-path "${KERNEL_PATH}" \
  --root "${ROOT_DIR}" \
  --org-id org_tutorial
echo ""

# ---- Step 2: Doctor check ----
echo "--- Step 2: Doctor ---"
"${LOOM}" doctor --root "${ROOT_DIR}" --format human
echo ""

# ---- Step 3: Build envelope ----
echo "--- Step 3: Build envelope ---"
"${LOOM}" envelope build \
  --root "${ROOT_DIR}" \
  --agent-id agent_tutorial \
  --org-id org_tutorial \
  --action-type research \
  --resource web_search \
  --estimated-cost-usd 0.05 \
  --format human
echo ""

# ---- Step 4: Enqueue action ----
echo "--- Step 4: Enqueue action ---"
"${LOOM}" action enqueue \
  --root "${ROOT_DIR}" \
  --agent-id agent_tutorial \
  --org-id org_tutorial \
  --action-type research \
  --resource web_search \
  --estimated-cost-usd 0.05 \
  --format human
echo ""

# ---- Step 5: List jobs ----
echo "--- Step 5: List queued jobs ---"
"${LOOM}" job list --root "${ROOT_DIR}" --format human
echo ""

# ---- Step 6: Run supervisor ----
echo "--- Step 6: Run supervisor ---"
"${LOOM}" supervisor run \
  --root "${ROOT_DIR}" \
  --kernel-path "${KERNEL_PATH}" \
  --max-jobs 1 \
  --format human
echo ""

# ---- Step 7: Inspect completed job ----
echo "--- Step 7: Inspect completed job ---"
JOB_ID="$(python3 - <<'PY' "${ROOT_DIR}"
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
payload = json.loads((root / "state" / "runtime" / "last_execution.json").read_text())
print(payload["input_hash"])
PY
)"
echo "job_id: ${JOB_ID}"
"${LOOM}" job inspect --root "${ROOT_DIR}" --job-id "${JOB_ID}" --format human
echo ""

# ---- Step 8: Parity and audit ----
echo "--- Step 8: Parity and audit trails ---"
"${LOOM}" parity report --root "${ROOT_DIR}"
"${LOOM}" shadow report --root "${ROOT_DIR}"
echo ""

echo "== First governed cell rehearsal complete =="
echo ""
echo "What you just proved:"
echo "  - Governed identity resolution works"
echo "  - Action envelopes are normalized and hashed"
echo "  - The queue boundary persists pending work"
echo "  - Governance gates fire on every action"
echo "  - Execution leaves auditable artifacts"
echo "  - Fail-closed is the default (try ./scripts/tests/rehearse_local_sanction_preview.sh)"
