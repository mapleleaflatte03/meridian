#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOOM="${LOOM:-${REPO_ROOT}/target/debug/loom}"
ROOT_DIR="${1:-/tmp/loom-clawskill-lifecycle}"
KERNEL_PATH="$(mktemp -d /tmp/loom-clawskill-lifecycle-kernel.XXXXXX)"
SKILL_ROOT="${SKILL_ROOT:-/root/.openclaw/workspace/skills/malware-triage}"

cleanup() {
  rm -rf "${ROOT_DIR}" "${KERNEL_PATH}"
}
trap cleanup EXIT

echo "== Meridian Loom // Clawfamily Skill Lifecycle =="
echo "root:   ${ROOT_DIR}"
echo "kernel: ${KERNEL_PATH}"
echo "skill:  ${SKILL_ROOT}"
echo "agent:  agent_tutorial"
echo "org:    org_tutorial"
echo ""

if [[ ! -x "${LOOM}" ]]; then
  echo "Binary not found at ${LOOM}, building..."
  (cd "${REPO_ROOT}" && cargo build --workspace)
fi

if [[ ! -f "${SKILL_ROOT}/SKILL.md" ]]; then
  echo "Expected workspace skill at ${SKILL_ROOT}" >&2
  exit 2
fi

rm -rf "${ROOT_DIR}"
mkdir -p "${KERNEL_PATH}/kernel/adapters"

cat > "${KERNEL_PATH}/kernel/runtimes.json" <<'EOF'
{
  "runtimes": {
    "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
    "meridian_loom": {
      "status": "experimental",
      "notes": "clawskill lifecycle rehearsal",
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

print(json.dumps({
    'id': 'agent_tutorial' if agent_id in ('agent_tutorial', 'tutorial', 'Tutorial') else agent_id,
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

cat > "${KERNEL_PATH}/kernel/audit.py" <<'EOF'
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

cat > "${KERNEL_PATH}/kernel/adapters/__init__.py" <<'EOF'
# fixture package
EOF

cat > "${KERNEL_PATH}/kernel/adapters/openclaw_compatible.py" <<'EOF'
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

export MERIDIAN_OPENCLAW_PROOF_SCRIPT="${KERNEL_PATH}/kernel/missing_openclaw_runtime_proof.py"

echo "--- Step 1: Initialize workspace ---"
"${LOOM}" init \
  --mode embedded \
  --kernel-path "${KERNEL_PATH}" \
  --root "${ROOT_DIR}" \
  --org-id org_tutorial
echo ""

echo "--- Step 2: Import workspace skill ---"
"${LOOM}" capability import-workspace-skill \
  --root "${ROOT_DIR}" \
  --skill-root "${SKILL_ROOT}"
echo ""

ARTIFACT_DIR="${ROOT_DIR}/samples"
mkdir -p "${ARTIFACT_DIR}"
python3 - <<'PY' "${ARTIFACT_DIR}/suspicious.exe"
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_bytes(b"MZ" + b"\x90" * 256)
print(path)
PY
echo ""

echo "--- Step 3: Verify imported capability through Loom runtime ---"
"${LOOM}" capability verify \
  --root "${ROOT_DIR}" \
  --kernel-path "${KERNEL_PATH}" \
  --agent-id agent_tutorial \
  --org-id org_tutorial \
  --name clawskill.malware-triage.v0 \
  --payload-json "{\"artifact_path\":\"${ARTIFACT_DIR}/suspicious.exe\",\"skip_container\":true}" \
  --estimated-cost-usd 0.05
echo ""

echo "--- Step 4: Promote verified capability ---"
"${LOOM}" capability promote \
  --root "${ROOT_DIR}" \
  --name clawskill.malware-triage.v0
echo ""

echo "--- Step 5: Show promoted capability ---"
"${LOOM}" capability show --root "${ROOT_DIR}" --name clawskill.malware-triage.v0
