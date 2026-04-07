#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-/tmp/loom-allow-execute}"
KERNEL_PATH="$(mktemp -d /tmp/loom-allow-kernel.XXXXXX)"
SOURCE_KERNEL="${SOURCE_KERNEL:-/tmp/meridian-kernel}"

cleanup() {
  rm -rf "${ROOT_DIR}" "${KERNEL_PATH}"
}
trap cleanup EXIT

echo "== Meridian Loom allow execute rehearsal =="
echo "root:   ${ROOT_DIR}"
echo "kernel: ${KERNEL_PATH}"
echo "agent:  agent_allow"
echo "org:    org_demo"

rm -rf "${ROOT_DIR}"
mkdir -p "${KERNEL_PATH}/kernel/adapters"

cat > "${KERNEL_PATH}/kernel/runtimes.json" <<'EOF'
{
  "runtimes": {
    "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
    "loom_native": {
      "status": "planned",
      "notes": "fixture-backed allow execute rehearsal",
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

if agent_id in ('agent_allow', 'allow', 'Allow'):
    print(json.dumps({
        'id': 'agent_allow',
        'name': 'Allow Path',
        'org_id': org_id,
        'role': 'analyst',
        'economy_key': 'allow',
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
import json
import os
import uuid

STORE = os.path.join(os.path.dirname(__file__), 'runtime_budget_reservations.json')

def _load():
    if os.path.exists(STORE):
        with open(STORE, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    return {'reservations': {}}

def _save(payload):
    with open(STORE, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)

def check_budget(agent_id, cost_usd, org_id=None):
    return True, 'ok'

def reserve_runtime_budget(agent_id, estimated_cost_usd, org_id=None, action='', resource='', context=None, policy_ref=''):
    payload = _load()
    reservation_id = f"res_{uuid.uuid4().hex[:10]}"
    payload['reservations'][reservation_id] = {
        'reservation_id': reservation_id,
        'agent_id': agent_id,
        'org_id': org_id or 'org_demo',
        'estimated_cost_usd': float(estimated_cost_usd),
        'actual_cost_usd': None,
        'action': action,
        'resource': resource,
        'context': context or {},
        'policy_ref': policy_ref,
        'status': 'reserved',
    }
    _save(payload)
    return {
        'allowed': True,
        'reservation_id': reservation_id,
        'reason': 'ok',
        'status': 'reserved',
    }

def commit_runtime_budget(reservation_id, actual_cost_usd, note=''):
    payload = _load()
    row = payload['reservations'][reservation_id]
    row['status'] = 'committed'
    row['actual_cost_usd'] = float(actual_cost_usd)
    row['commit_reason'] = note or 'worker_executed'
    _save(payload)
    return row

def release_runtime_budget(reservation_id, reason=''):
    payload = _load()
    row = payload['reservations'][reservation_id]
    row['status'] = 'released'
    row['release_reason'] = reason or 'released'
    _save(payload)
    return row

def expire_runtime_budget_reservations(org_id=None, now=None):
    return _load()

def budget_reservation_summary(org_id=None, agent_id=None):
    payload = _load()
    rows = list(payload['reservations'].values())
    return {
        'org_id': org_id,
        'agent_id': agent_id,
        'reservation_count': len(rows),
        'status_counts': {
            'reserved': sum(1 for row in rows if row.get('status') == 'reserved'),
            'committed': sum(1 for row in rows if row.get('status') == 'committed'),
            'released': sum(1 for row in rows if row.get('status') == 'released'),
        },
        'active_reserved_usd': round(sum(float(row.get('estimated_cost_usd', 0.0) or 0.0) for row in rows if row.get('status') == 'reserved'), 4),
        'committed_usd': round(sum(float((row.get('actual_cost_usd') if row.get('actual_cost_usd') is not None else row.get('estimated_cost_usd', 0.0)) or 0.0) for row in rows if row.get('status') == 'committed'), 4),
    }
EOF

cp "${SOURCE_KERNEL}/kernel/audit.py" "${KERNEL_PATH}/kernel/audit.py"

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

cargo build --workspace
export MERIDIAN_LEGACY_V1_PROOF_SCRIPT="${KERNEL_PATH}/kernel/missing_legacy_v1_runtime_proof.py"

./target/debug/loom init --mode embedded --kernel-path "${KERNEL_PATH}" --root "${ROOT_DIR}" --org-id org_demo
./target/debug/loom doctor --root "${ROOT_DIR}" --format human
./target/debug/loom action execute --root "${ROOT_DIR}" --agent-id agent_allow --org-id org_demo --action-type research --resource web_search --estimated-cost-usd 0.05 --format human
JOB_ID="$(basename "$(find "${ROOT_DIR}/state/runtime/jobs" -mindepth 1 -maxdepth 1 -type d | head -n1)")"
./target/debug/loom job inspect --root "${ROOT_DIR}" --job-id "${JOB_ID}" --format human
./target/debug/loom parity report --root "${ROOT_DIR}"
./target/debug/loom shadow report --root "${ROOT_DIR}"

echo "worker_result:"
cat "${ROOT_DIR}/state/runtime/jobs/"*/result.json
echo "audit_rows:"
cat "${KERNEL_PATH}/kernel/runtime_audit/loom_runtime_events.jsonl"

echo "== Allow execute rehearsal complete =="
