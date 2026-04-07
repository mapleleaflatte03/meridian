#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-/tmp/loom-commitment-import}"
KERNEL_PATH="$(mktemp -d /tmp/loom-commitment-import-kernel.XXXXXX)"
COMMITMENTS_PATH="${ROOT_DIR}/commitments_snapshot.json"

cleanup() {
  rm -rf "${ROOT_DIR}" "${KERNEL_PATH}"
}
trap cleanup EXIT

echo "== Meridian Loom commitment import rehearsal =="
echo "root:        ${ROOT_DIR}"
echo "kernel:      ${KERNEL_PATH}"
echo "commitments: ${COMMITMENTS_PATH}"

rm -rf "${ROOT_DIR}"
mkdir -p "${ROOT_DIR}" "${KERNEL_PATH}/kernel/adapters"

cat > "${KERNEL_PATH}/kernel/runtimes.json" <<'EOF'
{
  "runtimes": {
    "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
    "meridian_loom": {
      "status": "experimental",
      "notes": "commitment import rehearsal",
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
org_id = 'org_alpha'
if '--org_id' in sys.argv:
    org_id = sys.argv[sys.argv.index('--org_id') + 1]

print(json.dumps({
    'id': agent_id,
    'name': 'Atlas',
    'org_id': org_id,
    'role': 'analyst',
    'economy_key': 'atlas',
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
    ih = context.get('input_hash','') if context else ''
    return {"allowed": True, "reservation_id": f"res_{agent_id}_{ih}", "reason": "fixture budget ok"}
def commit_runtime_budget(reservation_id, actual_cost=0.0, note=''):
    return {"status": "committed", "reservation_id": reservation_id, "actual_cost": actual_cost}
def release_runtime_budget(reservation_id, reason=''):
    return {"status": "released", "reservation_id": reservation_id}
EOF

cat > "${KERNEL_PATH}/kernel/audit.py" <<'EOF'
def log_event(*args, **kwargs):
    return 'evt_import'
EOF

cargo build --workspace

./target/debug/loom init --mode embedded --kernel-path "${KERNEL_PATH}" --root "${ROOT_DIR}" --org-id org_alpha

cat > "${COMMITMENTS_PATH}" <<'EOF'
{
  "bound_org_id": "org_alpha",
  "commitments": [
    {
      "commitment_id": "commit_demo",
      "source_institution_id": "org_alpha",
      "delivery_refs": [
        {
          "message_type": "execution_request",
          "envelope_id": "fedenv_demo",
          "receipt_id": "fedrcpt_demo",
          "adapter_envelope": {
            "agent_id": "atlas",
            "action_type": "federated_execution",
            "resource": "host_beta/shared_brief_review",
            "estimated_cost_usd": 0.10,
            "run_id": "run_import_demo",
            "session_id": "sess_import_demo",
            "details": {
              "message_type": "execution_request",
              "commitment_id": "commit_demo"
            }
          }
        }
      ]
    }
  ]
}
EOF

import_json="$(
  ./target/debug/loom service import-commitments \
    --root "${ROOT_DIR}" \
    --kernel-path "${KERNEL_PATH}" \
    --commitments-source "${COMMITMENTS_PATH}" \
    --format json
)"
printf '%s\n' "${import_json}"
JOB_ID="$(
  printf '%s' "${import_json}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('last_job_id',''))"
)"

./target/debug/loom job list --root "${ROOT_DIR}" --format human
./target/debug/loom job inspect --job-id "${JOB_ID}" --root "${ROOT_DIR}" --format human

echo "import_markers:"
find "${ROOT_DIR}/state/runtime/imports" -maxdepth 3 -type f | sort

echo "== Commitment import rehearsal complete =="
