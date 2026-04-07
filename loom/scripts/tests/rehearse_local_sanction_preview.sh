#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-/tmp/loom-local-sanction-preview}"
KERNEL_PATH="$(mktemp -d /tmp/loom-local-kernel.XXXXXX)"

cleanup() {
  rm -rf "${ROOT_DIR}" "${KERNEL_PATH}"
}
trap cleanup EXIT

echo "== Meridian Loom local sanction preview =="
echo "root:   ${ROOT_DIR}"
echo "kernel: ${KERNEL_PATH}"
echo "agent:  agent_sanction"
echo "org:    org_demo"

rm -rf "${ROOT_DIR}"
mkdir -p "${KERNEL_PATH}/kernel/adapters"

cat > "${KERNEL_PATH}/kernel/runtimes.json" <<'EOF'
{
  "runtimes": {
    "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
    "loom_native": {
      "status": "planned",
      "notes": "fixture-backed local sanction preview",
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
org_id = 'org_demo'
if '--org_id' in sys.argv:
    org_id = sys.argv[sys.argv.index('--org_id') + 1]

if agent_id in ('agent_sanction', 'sanction', 'Sanction'):
    print(json.dumps({
        'id': 'agent_sanction',
        'name': 'Sanction Preview',
        'org_id': org_id,
        'role': 'analyst',
        'economy_key': 'sanction',
        'approval_required': False,
        'restrictions': ['execute'],
        'sanction_decision': 'restricted_execute',
        'budget': {'max_per_run_usd': 1.0},
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

cat > "${KERNEL_PATH}/kernel/audit.py" <<'EOF'
def log_event(*args, **kwargs):
    return 'evt_fixture'
EOF

cat > "${KERNEL_PATH}/kernel/metering.py" <<'EOF'
def record(*args, **kwargs):
    return 'meter_fixture'
EOF

cat > "${KERNEL_PATH}/kernel/adapters/__init__.py" <<'EOF'
# fixture package
EOF

cat > "${KERNEL_PATH}/kernel/adapters/legacy_v1_compatible.py" <<'EOF'
from audit import log_event
from authority import check_authority
from court import get_restrictions
from metering import record as meter_record
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

cargo build --workspace
export MERIDIAN_LEGACY_V1_PROOF_SCRIPT="${KERNEL_PATH}/kernel/missing_legacy_v1_runtime_proof.py"

./target/debug/loom init --mode embedded --kernel-path "${KERNEL_PATH}" --root "${ROOT_DIR}" --org-id org_demo
./target/debug/loom agent resolve --root "${ROOT_DIR}" --agent-id agent_sanction --org-id org_demo --format human
./target/debug/loom shadow decide --root "${ROOT_DIR}" --agent-id agent_sanction --org-id org_demo --action-type research --resource web_search --estimated-cost-usd 0.05 --format human
set +e
./target/debug/loom shadow enforce --root "${ROOT_DIR}" --agent-id agent_sanction --org-id org_demo --action-type research --resource web_search --estimated-cost-usd 0.05 --format human
ENFORCE_CODE=$?
set -e
echo "shadow_enforce_exit_code: ${ENFORCE_CODE}"
if [[ "${ENFORCE_CODE}" -ne 2 ]]; then
  echo "expected local sanction preview to fail closed with exit code 2"
  exit 1
fi
set +e
./target/debug/loom action execute --root "${ROOT_DIR}" --agent-id agent_sanction --org-id org_demo --action-type research --resource web_search --estimated-cost-usd 0.05 --format human
EXECUTE_CODE=$?
set -e
echo "action_execute_exit_code: ${EXECUTE_CODE}"
if [[ "${EXECUTE_CODE}" -ne 2 ]]; then
  echo "expected local sanction action execute to fail closed with exit code 2"
  exit 1
fi
./target/debug/loom shadow report --root "${ROOT_DIR}"
./target/debug/loom parity report --root "${ROOT_DIR}"

echo "== Local sanction preview rehearsal complete =="
