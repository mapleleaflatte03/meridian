#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOOM="${LOOM:-${REPO_ROOT}/target/debug/loom}"
ROOT_DIR="${ROOT_DIR:-$(mktemp -d /tmp/meridian-loom-acceptance.XXXXXX)}"
SOURCE_KERNEL="${SOURCE_KERNEL:-/opt/meridian-kernel}"
FIXTURE_KERNEL="$(mktemp -d /tmp/meridian-loom-acceptance-kernel.XXXXXX)"
TMP_DIR="$(mktemp -d /tmp/meridian-loom-acceptance-tmp.XXXXXX)"
SERVICE_TOKEN="${SERVICE_TOKEN:-loom-acceptance-token}"
ORG_ID="${ORG_ID:-local_foundry}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT_DIR="$2"
      shift 2
      ;;
    --kernel-path)
      SOURCE_KERNEL="$2"
      shift 2
      ;;
    --service-token)
      SERVICE_TOKEN="$2"
      shift 2
      ;;
    --org-id)
      ORG_ID="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

cleanup() {
  rm -rf "${FIXTURE_KERNEL}" "${TMP_DIR}"
}
trap cleanup EXIT

export LOOM_SERVICE_TOKEN="${SERVICE_TOKEN}"

(cd "${REPO_ROOT}" && cargo build >/dev/null)

rm -rf "${ROOT_DIR}"
mkdir -p "${ROOT_DIR}"
mkdir -p "${FIXTURE_KERNEL}/kernel/adapters"

cat > "${FIXTURE_KERNEL}/kernel/runtimes.json" <<'EOF'
{
  "runtimes": {
    "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
    "loom_native": {
      "status": "experimental",
      "notes": "acceptance fixture",
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

cat > "${FIXTURE_KERNEL}/kernel/agent_registry.py" <<'EOF'
import json
import sys

agent_id = sys.argv[sys.argv.index('--agent_id') + 1]
org_id = 'local_foundry'
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

cat > "${FIXTURE_KERNEL}/kernel/court.py" <<'EOF'
def get_restrictions(agent_id, org_id=None):
    return []
EOF

cat > "${FIXTURE_KERNEL}/kernel/authority.py" <<'EOF'
def check_authority(agent_id, action, org_id=None):
    return True, 'ok'
EOF

cat > "${FIXTURE_KERNEL}/kernel/treasury.py" <<'EOF'
def check_budget(agent_id, cost_usd, org_id=None):
    return True, 'ok'

def reserve_runtime_budget(agent_id, estimated_cost_usd, org_id=None, action='', resource='', context=None, policy_ref='', lease_seconds=60):
    return {
        'allowed': True,
        'reservation_id': 'bud_acceptance',
        'reservation': {
            'reservation_id': 'bud_acceptance',
            'status': 'reserved',
            'estimated_cost_usd': estimated_cost_usd
        },
        'reason': 'ok',
    }

def commit_runtime_budget(reservation_id, actual_cost_usd, note=''):
    return {
        'reservation_id': reservation_id,
        'status': 'committed',
        'commit_reason': note,
    }

def release_runtime_budget(reservation_id, reason=''):
    return {
        'reservation_id': reservation_id,
        'status': 'released',
        'release_reason': reason,
    }
EOF

if [[ -f "${SOURCE_KERNEL}/kernel/audit.py" ]]; then
  cp "${SOURCE_KERNEL}/kernel/audit.py" "${FIXTURE_KERNEL}/kernel/audit.py"
else
  cat > "${FIXTURE_KERNEL}/kernel/audit.py" <<'EOF'
import json
import pathlib
import time

def log_runtime(event_type, payload, kernel_path=None):
    target = pathlib.Path(kernel_path or '.') / 'kernel' / 'runtime_audit' / 'loom_runtime_events.jsonl'
    target.parent.mkdir(parents=True, exist_ok=True)
    entry = {'ts': time.time(), 'event_type': event_type, **payload}
    with open(target, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry) + '\n')
EOF
fi

cat > "${FIXTURE_KERNEL}/kernel/adapters/__init__.py" <<'EOF'
# acceptance fixture package
EOF

cat > "${FIXTURE_KERNEL}/kernel/adapters/legacy_v1_compatible.py" <<'EOF'
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

"${LOOM}" init --mode embedded --root "${ROOT_DIR}" --kernel-path "${FIXTURE_KERNEL}" --org-id "${ORG_ID}"
"${LOOM}" doctor --root "${ROOT_DIR}" --format human
"${LOOM}" health --root "${ROOT_DIR}" --format human
"${LOOM}" start --root "${ROOT_DIR}" --kernel-path "${FIXTURE_KERNEL}" --http-address 127.0.0.1:0 --service-token "${SERVICE_TOKEN}" --max-jobs 1 --poll-seconds 1 --iterations 1000000 --format human

STATE_PATH="${ROOT_DIR}/run/service/runtime_state.json"
for _ in $(seq 1 50); do
  if [[ -f "${STATE_PATH}" ]]; then
    break
  fi
  sleep 0.2
done

if [[ ! -f "${STATE_PATH}" ]]; then
  echo "runtime state was not created at ${STATE_PATH}" >&2
  exit 1
fi

HTTP_ADDRESS="$(
  python3 - <<'PY' "${STATE_PATH}"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    data = json.load(handle)
print(data.get("http_address") or "")
PY
)"

HTTP_URL=""
HTTP_TRANSPORT="file_fallback"
"${LOOM}" status --root "${ROOT_DIR}"

if [[ -n "${HTTP_ADDRESS}" ]]; then
  HTTP_URL="http://${HTTP_ADDRESS}"
  HTTP_TRANSPORT="http"

  curl -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/status" >"${TMP_DIR}/status.json"
  curl -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/health" >"${TMP_DIR}/health.json"
  curl -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/metrics" >"${TMP_DIR}/metrics.json"
  curl -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/config" >"${TMP_DIR}/config.json"

  BAD_TOKEN_STATUS="$(curl -sS -o "${TMP_DIR}/bad-token.json" -w '%{http_code}' -H 'Authorization: Bearer wrong-token' "${HTTP_URL}/status")"
  if [[ "${BAD_TOKEN_STATUS}" != "401" ]]; then
    echo "expected bad token request to return 401, got ${BAD_TOKEN_STATUS}" >&2
    exit 1
  fi

  BAD_REQUEST_STATUS="$(printf 'GET /status HTTP/1.1\r\nHost: acceptance\r\nContent-Length: nope\r\n\r\n' | python3 - <<'PY' "${HTTP_ADDRESS}"
import socket
import sys

host, port = sys.argv[1].split(":")
payload = sys.stdin.buffer.read()
with socket.create_connection((host, int(port)), timeout=5) as sock:
    sock.sendall(payload)
    sock.shutdown(socket.SHUT_WR)
    data = sock.recv(4096).decode("utf-8", "replace")
print(data.split()[1] if data else "")
PY
  )"
  if [[ "${BAD_REQUEST_STATUS}" != "400" ]]; then
    echo "expected malformed request to return 400, got ${BAD_REQUEST_STATUS}" >&2
    exit 1
  fi
fi

submit_payload="$(cat <<JSON
{
  "request_id": "acceptance-submit",
  "agent_id": "agent_allow",
  "org_id": "${ORG_ID}",
  "action_type": "research",
  "resource": "web_search",
  "estimated_cost_usd": 0.05,
  "run_id": "acceptance-run",
  "session_id": "acceptance-session",
  "kernel_path": "${FIXTURE_KERNEL}"
}
JSON
)"

if [[ "${HTTP_TRANSPORT}" == "http" ]]; then
  SUBMIT_JSON="$(curl -sS \
    -H "Authorization: Bearer ${SERVICE_TOKEN}" \
    -H 'Content-Type: application/json' \
    -X POST \
    --data "${submit_payload}" \
    "${HTTP_URL}/submit")"
  printf '%s\n' "${SUBMIT_JSON}" >"${TMP_DIR}/submit.json"

  BAD_MEDIA_STATUS="$(curl -sS -o "${TMP_DIR}/bad-media.json" -w '%{http_code}' \
    -H "Authorization: Bearer ${SERVICE_TOKEN}" \
    -H 'Content-Type: text/plain' \
    -X POST \
    --data "${submit_payload}" \
    "${HTTP_URL}/submit")"
  if [[ "${BAD_MEDIA_STATUS}" != "415" ]]; then
    echo "expected wrong content-type to return 415, got ${BAD_MEDIA_STATUS}" >&2
    exit 1
  fi

  BAD_JSON_STATUS="$(curl -sS -o "${TMP_DIR}/bad-json.json" -w '%{http_code}' \
    -H "Authorization: Bearer ${SERVICE_TOKEN}" \
    -H 'Content-Type: application/json' \
    -X POST \
    --data '{"request_id":"bad-json",' \
    "${HTTP_URL}/submit")"
  if [[ "${BAD_JSON_STATUS}" != "400" ]]; then
    echo "expected malformed JSON to return 400, got ${BAD_JSON_STATUS}" >&2
    exit 1
  fi
else
  SUBMIT_JSON="$("${LOOM}" service submit \
    --root "${ROOT_DIR}" \
    --service-token "${SERVICE_TOKEN}" \
    --agent-id agent_allow \
    --org-id "${ORG_ID}" \
    --action-type research \
    --resource web_search \
    --estimated-cost-usd 0.05 \
    --run-id acceptance-run \
    --session-id acceptance-session \
    --kernel-path "${FIXTURE_KERNEL}" \
    --format json)"
  printf '%s\n' "${SUBMIT_JSON}" >"${TMP_DIR}/submit.json"
fi

JOB_ID="$(
  python3 - <<'PY' "${TMP_DIR}/submit.json"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    data = json.load(handle)
print(data.get("job_id", ""))
PY
)"

if [[ -z "${JOB_ID}" ]]; then
  echo "submit did not return a job_id" >&2
  exit 1
fi

for _ in $(seq 1 50); do
  JOB_JSON="$("${LOOM}" job inspect --root "${ROOT_DIR}" --job-id "${JOB_ID}" --format json || true)"
  if [[ -n "${JOB_JSON}" ]] && printf '%s' "${JOB_JSON}" | grep -q '"job_status": "completed"'; then
    break
  fi
  sleep 0.2
done

"${LOOM}" job inspect --root "${ROOT_DIR}" --job-id "${JOB_ID}" --format human
if [[ "${HTTP_TRANSPORT}" == "http" ]]; then
  curl -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/jobs/${JOB_ID}" >"${TMP_DIR}/job.json"
fi
"${LOOM}" logs --root "${ROOT_DIR}" --lines 20
RESTART_ARGS=(
  "${LOOM}" restart
  --root "${ROOT_DIR}"
  --kernel-path "${FIXTURE_KERNEL}"
  --service-token "${SERVICE_TOKEN}"
  --max-jobs 1
  --poll-seconds 1
  --iterations 1000000
  --format human
)
if [[ -n "${HTTP_ADDRESS}" ]]; then
  RESTART_ARGS+=(--http-address "${HTTP_ADDRESS}")
fi
"${RESTART_ARGS[@]}"
"${LOOM}" stop --root "${ROOT_DIR}" --format human
"${LOOM}" stop --root "${ROOT_DIR}" --format human
"${LOOM}" status --root "${ROOT_DIR}"

echo "root=${ROOT_DIR}"
echo "kernel_source=${SOURCE_KERNEL}"
echo "kernel_fixture=${FIXTURE_KERNEL}"
echo "transport=${HTTP_TRANSPORT}"
echo "http_url=${HTTP_URL:-disabled}"
echo "job_id=${JOB_ID}"
echo "config=${ROOT_DIR}/loom.toml"
echo "state=${ROOT_DIR}/state"
echo "run=${ROOT_DIR}/run"
echo "logs=${ROOT_DIR}/logs"
echo "artifacts=${ROOT_DIR}/artifacts"
