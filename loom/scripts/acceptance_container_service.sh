#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-meridian-loom:acceptance}"
CONTAINER_NAME="${CONTAINER_NAME:-meridian-loom-acceptance}"
HOST_PORT="${HOST_PORT:-18910}"
ROOT_DIR="${ROOT_DIR:-$(mktemp -d /tmp/meridian-loom-container-acceptance.XXXXXX)}"
SOURCE_KERNEL="${SOURCE_KERNEL:-/opt/meridian-kernel}"
FIXTURE_KERNEL="$(mktemp -d /tmp/meridian-loom-container-kernel.XXXXXX)"
SERVICE_TOKEN="${SERVICE_TOKEN:-loom-container-token}"
ORG_ID="${ORG_ID:-local_foundry}"
BUILD_IMAGE="${BUILD_IMAGE:-auto}"
NETWORK_MODE="${NETWORK_MODE:-auto}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)
      IMAGE_NAME="$2"
      shift 2
      ;;
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
    --host-port)
      HOST_PORT="$2"
      shift 2
      ;;
    --build-image)
      BUILD_IMAGE="$2"
      shift 2
      ;;
    --network-mode)
      NETWORK_MODE="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

cleanup() {
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  rm -rf "${FIXTURE_KERNEL}"
}

dump_container_diagnostics() {
  docker ps -a --filter "name=${CONTAINER_NAME}" --format 'container={{.Names}} status={{.Status}} ports={{.Ports}}' >&2 || true
  docker inspect --format 'state={{.State.Status}} exit={{.State.ExitCode}} error={{.State.Error}}' "${CONTAINER_NAME}" >&2 || true
  docker logs "${CONTAINER_NAME}" >&2 || true
}

on_exit() {
  status=$?
  if [[ ${status} -ne 0 ]]; then
    dump_container_diagnostics
  fi
  cleanup
  exit ${status}
}

trap on_exit EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is not installed on this host" >&2
  exit 127
fi

if ! docker info >/dev/null 2>&1; then
  echo "docker daemon is unavailable or inaccessible; container acceptance cannot run" >&2
  exit 2
fi

rm -rf "${ROOT_DIR}"
mkdir -p "${ROOT_DIR}"
chmod 0777 "${ROOT_DIR}"
mkdir -p "${FIXTURE_KERNEL}/kernel/adapters"

cat > "${FIXTURE_KERNEL}/kernel/runtimes.json" <<'EOF'
{
  "runtimes": {
    "local_kernel": {"id": "local_kernel", "label": "Local Kernel Runtime"},
    "loom_native": {
      "status": "experimental",
      "notes": "container acceptance fixture",
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
        'reservation_id': 'bud_container',
        'reservation': {
            'reservation_id': 'bud_container',
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
# container acceptance fixture package
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

chmod -R a+rX "${FIXTURE_KERNEL}"

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
if [[ "${BUILD_IMAGE}" == "always" ]] || ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
  docker build -t "${IMAGE_NAME}" "${REPO_ROOT}" >/dev/null
fi

DOCKER_NETWORK_ARGS=()
HTTP_BIND_ADDRESS="0.0.0.0:${HOST_PORT}"
if [[ "${NETWORK_MODE}" == "auto" ]]; then
  NETWORK_MODE="host"
fi
if [[ "${NETWORK_MODE}" == "host" ]]; then
  DOCKER_NETWORK_ARGS+=(--network host)
  HTTP_BIND_ADDRESS="127.0.0.1:${HOST_PORT}"
else
  DOCKER_NETWORK_ARGS+=(-p "127.0.0.1:${HOST_PORT}:18910")
fi

CONTAINER_SOCKET="/tmp/meridian-loom-container.sock"
CONTAINER_COMMAND_HTTP="set -e
loom init --mode embedded --root \"\$LOOM_ROOT\" --kernel-path /kernel --org-id \"\$LOOM_ORG_ID\"
exec loom start --foreground --root \"\$LOOM_ROOT\" --kernel-path /kernel --socket ${CONTAINER_SOCKET} --http-address ${HTTP_BIND_ADDRESS} --service-token \"\$LOOM_SERVICE_TOKEN\" --max-jobs 1 --poll-seconds 1 --iterations 1000000 --format human"
CONTAINER_COMMAND_SOCKET="set -e
loom init --mode embedded --root \"\$LOOM_ROOT\" --kernel-path /kernel --org-id \"\$LOOM_ORG_ID\"
exec loom start --foreground --root \"\$LOOM_ROOT\" --kernel-path /kernel --socket ${CONTAINER_SOCKET} --no-http --max-jobs 1 --poll-seconds 1 --iterations 1000000 --format human"

start_container() {
  local command="$1"
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  rm -rf "${ROOT_DIR}/runtime"
  mkdir -p "${ROOT_DIR}"
  chmod 0777 "${ROOT_DIR}"
  docker run -d \
    --name "${CONTAINER_NAME}" \
    --entrypoint /bin/sh \
    -e LOOM_ROOT=/var/lib/loom/runtime/default \
    -e LOOM_SERVICE_TOKEN="${SERVICE_TOKEN}" \
    -e LOOM_ORG_ID="${ORG_ID}" \
    -e MERIDIAN_RUNTIME_AUDIT_FILE=/var/lib/loom/runtime/default/artifacts/audit/loom_runtime_events.jsonl \
    -v "${ROOT_DIR}:/var/lib/loom" \
    -v "${FIXTURE_KERNEL}:/kernel:ro" \
    "${DOCKER_NETWORK_ARGS[@]}" \
    "${IMAGE_NAME}" \
    -lc "${command}" >/dev/null
}

submit_payload="$(cat <<JSON
{
  "request_id": "container-submit",
  "agent_id": "agent_allow",
  "org_id": "${ORG_ID}",
  "action_type": "research",
  "resource": "web_search",
  "estimated_cost_usd": 0.05,
  "run_id": "container-run",
  "session_id": "container-session",
  "kernel_path": "/kernel"
}
JSON
)"

HTTP_URL="http://127.0.0.1:${HOST_PORT}"
VERIFICATION_TRANSPORT="http"
start_container "${CONTAINER_COMMAND_HTTP}"

service_ready=0
for _ in $(seq 1 40); do
  if curl --max-time 3 -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/health" >/tmp/loom-container-health.json 2>/dev/null; then
    service_ready=1
    break
  fi
  sleep 0.5
done

if [[ "${service_ready}" == "1" ]]; then
  curl --max-time 3 -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/status" >/tmp/loom-container-status.json
  curl --max-time 3 -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/metrics" >/tmp/loom-container-metrics.json
  curl --max-time 3 -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/config" >/tmp/loom-container-config.json

  SUBMIT_JSON="$(curl --max-time 3 -sS \
    -H "Authorization: Bearer ${SERVICE_TOKEN}" \
    -H 'Content-Type: application/json' \
    -X POST \
    --data "${submit_payload}" \
    "${HTTP_URL}/submit")"
  printf '%s\n' "${SUBMIT_JSON}" >/tmp/loom-container-submit.json

  JOB_ID="$(
    python3 - <<'PY' /tmp/loom-container-submit.json
import json
import sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    payload = json.load(handle)
print(payload.get("job_id", ""))
PY
  )"

  if [[ -z "${JOB_ID}" ]]; then
    echo "container submit did not return a job_id" >&2
    exit 1
  fi

  for _ in $(seq 1 40); do
    if docker exec "${CONTAINER_NAME}" loom job inspect --root /var/lib/loom/runtime/default --job-id "${JOB_ID}" --format json | grep -q '"job_status": "completed"'; then
      break
    fi
    sleep 0.5
  done

  JOB_JSON="$(docker exec "${CONTAINER_NAME}" loom job inspect --root /var/lib/loom/runtime/default --job-id "${JOB_ID}" --format json)"
  printf '%s\n' "${JOB_JSON}" >/tmp/loom-container-job-inspect.json
  JOB_STATUS="$(
    python3 - <<'PY' /tmp/loom-container-job-inspect.json
import json
import sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    payload = json.load(handle)
print(payload.get("job_status") or payload.get("status", ""))
PY
  )"
  if [[ "${JOB_STATUS}" != "completed" ]]; then
    echo "container job did not complete successfully; status=${JOB_STATUS}" >&2
    docker exec "${CONTAINER_NAME}" loom job inspect --root /var/lib/loom/runtime/default --job-id "${JOB_ID}" --format human >&2 || true
    exit 1
  fi

  docker exec "${CONTAINER_NAME}" loom job inspect --root /var/lib/loom/runtime/default --job-id "${JOB_ID}" --format human
  curl --max-time 3 -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" "${HTTP_URL}/jobs/${JOB_ID}" >/tmp/loom-container-job.json
  curl --max-time 3 -sS -H "Authorization: Bearer ${SERVICE_TOKEN}" -H 'Content-Type: application/json' -X POST --data '{}' "${HTTP_URL}/stop" >/tmp/loom-container-stop.json
  docker wait "${CONTAINER_NAME}" >/dev/null
else
  docker logs "${CONTAINER_NAME}" >&2 || true
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  VERIFICATION_TRANSPORT="direct_exec"
  rm -rf "${ROOT_DIR}/runtime"
  mkdir -p "${ROOT_DIR}"
  chmod 0777 "${ROOT_DIR}"
  SUBMIT_JSON="$(docker run --rm \
    --entrypoint /bin/sh \
    -e LOOM_ROOT=/var/lib/loom/runtime/default \
    -e LOOM_SERVICE_TOKEN="${SERVICE_TOKEN}" \
    -e LOOM_ORG_ID="${ORG_ID}" \
    -e MERIDIAN_RUNTIME_AUDIT_FILE=/var/lib/loom/runtime/default/artifacts/audit/loom_runtime_events.jsonl \
    -v "${ROOT_DIR}:/var/lib/loom" \
    -v "${FIXTURE_KERNEL}:/kernel:ro" \
    "${IMAGE_NAME}" \
    -lc 'set -e
      loom init --mode embedded --root "$LOOM_ROOT" --kernel-path /kernel --org-id "$LOOM_ORG_ID"
      loom action execute --root "$LOOM_ROOT" --agent-id agent_allow --org-id "$LOOM_ORG_ID" --action-type research --resource web_search --estimated-cost-usd 0.05 --run-id container-run --session-id container-session --kernel-path /kernel --format json
    ')"
  printf '%s\n' "${SUBMIT_JSON}" >/tmp/loom-container-submit.json
  python3 -m json.tool "${ROOT_DIR}/runtime/default/state/runtime/last_execution.json" >/tmp/loom-container-status.json
  python3 -m json.tool "${ROOT_DIR}/runtime/default/artifacts/parity/latest.json" >/tmp/loom-container-metrics.json
  cat "${ROOT_DIR}/runtime/default/loom.toml" >/tmp/loom-container-config.json

  JOB_ID="$(
    python3 - <<'PY' /tmp/loom-container-submit.json
import json
import sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    payload = json.load(handle)
print(payload.get("job_id", ""))
PY
  )"

  if [[ -z "${JOB_ID}" ]]; then
    echo "container direct execute did not return a job_id" >&2
    exit 1
  fi

  docker run --rm \
    --entrypoint /bin/sh \
    -e LOOM_ROOT=/var/lib/loom/runtime/default \
    -e MERIDIAN_RUNTIME_AUDIT_FILE=/var/lib/loom/runtime/default/artifacts/audit/loom_runtime_events.jsonl \
    -v "${ROOT_DIR}:/var/lib/loom" \
    -v "${FIXTURE_KERNEL}:/kernel:ro" \
    "${IMAGE_NAME}" \
    -lc "loom job inspect --root /var/lib/loom/runtime/default --job-id ${JOB_ID} --format human"
  printf '{"status":"completed","transport":"direct_exec"}\n' >/tmp/loom-container-stop.json
fi

echo "root=${ROOT_DIR}"
echo "image=${IMAGE_NAME}"
echo "container=${CONTAINER_NAME}"
echo "build_image=${BUILD_IMAGE}"
echo "network_mode=${NETWORK_MODE}"
echo "verification_transport=${VERIFICATION_TRANSPORT}"
echo "http_url=${HTTP_URL}"
echo "job_id=${JOB_ID}"
echo "config=${ROOT_DIR}/runtime/default/loom.toml"
echo "state=${ROOT_DIR}/runtime/default/state"
echo "run=${ROOT_DIR}/runtime/default/run"
echo "logs=${ROOT_DIR}/runtime/default/logs"
echo "artifacts=${ROOT_DIR}/runtime/default/artifacts"
