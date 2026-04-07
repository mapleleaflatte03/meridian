#!/usr/bin/env bash
set -euo pipefail

write_local_fixture_kernel() {
  local kernel_root="$1"
  local note="${2:-local fixture}"
  mkdir -p "${kernel_root}/kernel/adapters"

  cat > "${kernel_root}/kernel/runtimes.json" <<EOF
{
  "runtimes": {
    "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
    "loom_native": {
      "status": "experimental",
      "notes": "${note}",
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

  cat > "${kernel_root}/kernel/agent_registry.py" <<'EOF'
import json
import sys

agent_id = sys.argv[sys.argv.index('--agent_id') + 1]
org_id = 'local_foundry'
if '--org_id' in sys.argv:
    org_id = sys.argv[sys.argv.index('--org_id') + 1]

record = {
    'id': agent_id,
    'name': agent_id.replace('_', ' ').title(),
    'org_id': org_id,
    'role': 'analyst',
    'economy_key': 'fixture',
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
}
print(json.dumps(record, indent=2))
EOF

  cat > "${kernel_root}/kernel/court.py" <<'EOF'
def get_restrictions(agent_id, org_id=None):
    return []
EOF

  cat > "${kernel_root}/kernel/authority.py" <<'EOF'
def check_authority(agent_id, action, org_id=None):
    return True, 'ok'
EOF

  cat > "${kernel_root}/kernel/treasury.py" <<'EOF'
def check_budget(agent_id, cost_usd, org_id=None):
    return True, 'ok'

def reserve_runtime_budget(agent_id, estimated_cost, org_id=None, action=None, resource=None, context=None, policy_ref=None):
    input_hash = ''
    if context:
        input_hash = context.get('input_hash', '')
    return {
        'allowed': True,
        'reservation_id': f'res_{agent_id}_{input_hash}',
        'reservation': {'reservation_id': f'res_{agent_id}_{input_hash}'},
        'reason': 'fixture budget ok'
    }

def commit_runtime_budget(reservation_id, actual_cost=0.0, note=''):
    return {'status': 'committed', 'reservation_id': reservation_id, 'actual_cost': actual_cost}

def release_runtime_budget(reservation_id, reason=''):
    return {'status': 'released', 'reservation_id': reservation_id, 'reason': reason}
EOF

  cat > "${kernel_root}/kernel/audit.py" <<'EOF'
import json
import os
import sys
import time

RUNTIME_AUDIT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime_audit", "loom_runtime_events.jsonl")

def _ensure_parent(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def log_runtime(event_type, payload, kernel_path=None):
    target = os.environ.get('MERIDIAN_RUNTIME_AUDIT_FILE') or RUNTIME_AUDIT_FILE
    _ensure_parent(target)
    entry = {'ts': int(time.time()), 'event_type': event_type, **payload}
    with open(target, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry, sort_keys=True) + '\n')
    return 'fixture_runtime_audit_written'

if __name__ == '__main__':
    if 'log-runtime' in sys.argv:
        idx = sys.argv.index('log-runtime')
        event_type = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else 'unknown'
        payload_str = sys.argv[idx + 2] if len(sys.argv) > idx + 2 else '{}'
        kernel_path = None
        if '--kernel-path' in sys.argv:
            kernel_path = sys.argv[sys.argv.index('--kernel-path') + 1]
        print(log_runtime(event_type, json.loads(payload_str), kernel_path=kernel_path))
EOF

  cat > "${kernel_root}/kernel/adapters/__init__.py" <<'EOF'
# fixture package
EOF

  cat > "${kernel_root}/kernel/adapters/legacy_v1_compatible.py" <<'EOF'
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
}

ensure_debug_loom_binary() {
  local repo_root="$1"
  (cd "${repo_root}" && cargo build --workspace >/dev/null)
}
