#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/fixture_kernel_local.sh"

LOOM="${LOOM:-${REPO_ROOT}/target/debug/loom}"
ROOT_DIR="${ROOT_DIR:-$(mktemp -d /tmp/meridian-loom-capability-service.XXXXXX)}"
FIXTURE_KERNEL="$(mktemp -d /tmp/meridian-loom-capability-service-kernel.XXXXXX)"
TMP_DIR="$(mktemp -d /tmp/meridian-loom-capability-service-tmp.XXXXXX)"
SERVICE_TOKEN="${SERVICE_TOKEN:-loom-capability-service-token}"
ORG_ID="${ORG_ID:-local_foundry}"
CAPABILITY_NAME="${CAPABILITY_NAME:-loom.echo.v1}"
MESSAGE_ONE="${MESSAGE_ONE:-hello from capability service}"
MESSAGE_TWO="${MESSAGE_TWO:-hello after restart}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT_DIR="$2"; shift 2 ;;
    --service-token) SERVICE_TOKEN="$2"; shift 2 ;;
    --org-id) ORG_ID="$2"; shift 2 ;;
    --capability) CAPABILITY_NAME="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

cleanup() {
  rm -rf "${FIXTURE_KERNEL}" "${TMP_DIR}"
}
trap cleanup EXIT

export LOOM_SERVICE_TOKEN="${SERVICE_TOKEN}"
export MERIDIAN_LEGACY_V1_PROOF_SCRIPT="${FIXTURE_KERNEL}/kernel/missing_legacy_v1_runtime_proof.py"

ensure_debug_loom_binary "${REPO_ROOT}"
rm -rf "${ROOT_DIR}"
mkdir -p "${ROOT_DIR}"
write_local_fixture_kernel "${FIXTURE_KERNEL}" "capability service acceptance"

read_json_field() {
  python3 - <<'PY' "$1" "$2"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    data = json.load(handle)
value = data
for part in sys.argv[2].split('.'):
    if part:
        value = value.get(part) if isinstance(value, dict) else None
print("" if value is None else value)
PY
}

assert_file_contains() {
  local file="$1"
  local needle="$2"
  if ! grep -q --fixed-strings "${needle}" "${file}"; then
    echo "expected ${file} to contain ${needle}" >&2
    exit 1
  fi
}

wait_for_service_ready() {
  local state_path="$1"
  for _ in $(seq 1 60); do
    if [[ -f "${state_path}" ]] && python3 - <<'PY' "${state_path}"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    data = json.load(handle)
raise SystemExit(0 if data.get("running") else 1)
PY
    then
      return 0
    fi
    sleep 0.2
  done
  echo "service did not report running via ${state_path}" >&2
  exit 1
}

wait_for_completed_job() {
  local job_id="$1"
  local last_json=""
  for _ in $(seq 1 50); do
    last_json="$("${LOOM}" job inspect --root "${ROOT_DIR}" --job-id "${job_id}" --format json || true)"
    if [[ -n "${last_json}" ]] && printf '%s' "${last_json}" | grep -q '"job_status": "completed"'; then
      printf '%s' "${last_json}"
      return 0
    fi
    sleep 0.2
  done
  echo "job ${job_id} did not complete" >&2
  exit 1
}

"${LOOM}" init --mode embedded --root "${ROOT_DIR}" --kernel-path "${FIXTURE_KERNEL}" --org-id "${ORG_ID}"

DIRECT_JSON="$("${LOOM}" action execute \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --agent-id agent_allow \
  --org-id "${ORG_ID}" \
  --capability "${CAPABILITY_NAME}" \
  --payload-json "{\"message\":\"${MESSAGE_ONE}\"}" \
  --estimated-cost-usd 0.05 \
  --format json)"
printf '%s\n' "${DIRECT_JSON}" >"${TMP_DIR}/direct.json"
DIRECT_RESULT_PATH="$(read_json_field "${TMP_DIR}/direct.json" "worker_result_path")"
if [[ -z "${DIRECT_RESULT_PATH}" || ! -f "${DIRECT_RESULT_PATH}" ]]; then
  echo "direct capability path did not produce worker_result_path" >&2
  exit 1
fi
assert_file_contains "${DIRECT_RESULT_PATH}" "\"capability_name\": \"${CAPABILITY_NAME}\""
assert_file_contains "${DIRECT_RESULT_PATH}" "${MESSAGE_ONE}"

"${LOOM}" start \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --http-address 127.0.0.1:0 \
  --service-token "${SERVICE_TOKEN}" \
  --max-jobs 1 \
  --poll-seconds 1 \
  --iterations 1000000 \
  --format human

STATE_PATH="${ROOT_DIR}/run/service/runtime_state.json"
wait_for_service_ready "${STATE_PATH}"

HTTP_ADDRESS="$(read_json_field "${STATE_PATH}" "http_address")"
HTTP_URL=""
TRANSPORT="file_ingress"
if [[ -n "${HTTP_ADDRESS}" ]]; then
  HTTP_URL="http://${HTTP_ADDRESS}"
  TRANSPORT="http"
fi

if [[ "${TRANSPORT}" == "http" ]]; then
  SUBMIT_ONE="$(curl -sS \
    -H "Authorization: Bearer ${SERVICE_TOKEN}" \
    -H 'Content-Type: application/json' \
    -X POST \
    --data "{\"request_id\":\"capability-service-1\",\"agent_id\":\"agent_allow\",\"org_id\":\"${ORG_ID}\",\"capability_name\":\"${CAPABILITY_NAME}\",\"payload_json\":{\"message\":\"${MESSAGE_ONE}\"},\"estimated_cost_usd\":0.05,\"kernel_path\":\"${FIXTURE_KERNEL}\"}" \
    "${HTTP_URL}/submit")"
else
  SUBMIT_ONE="$("${LOOM}" service submit \
    --root "${ROOT_DIR}" \
    --kernel-path "${FIXTURE_KERNEL}" \
    --service-token "${SERVICE_TOKEN}" \
    --agent-id agent_allow \
    --org-id "${ORG_ID}" \
    --capability "${CAPABILITY_NAME}" \
    --payload-json "{\"message\":\"${MESSAGE_ONE}\"}" \
    --estimated-cost-usd 0.05 \
    --format json)"
fi
printf '%s\n' "${SUBMIT_ONE}" >"${TMP_DIR}/submit-one.json"
JOB_ONE="$(read_json_field "${TMP_DIR}/submit-one.json" "job_id")"
if [[ -z "${JOB_ONE}" ]]; then
  echo "first service submit did not return job_id" >&2
  exit 1
fi
wait_for_completed_job "${JOB_ONE}" >"${TMP_DIR}/job-one.json"
JOB_ONE_PATH="$(read_json_field "${TMP_DIR}/job-one.json" "job_path")"
JOB_ONE_RESULT="$(dirname "${JOB_ONE_PATH}")/result.json"
assert_file_contains "${JOB_ONE_RESULT}" "\"capability_name\": \"${CAPABILITY_NAME}\""
assert_file_contains "${JOB_ONE_RESULT}" "${MESSAGE_ONE}"

"${LOOM}" restart \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --http-address "${HTTP_ADDRESS:-127.0.0.1:0}" \
  --service-token "${SERVICE_TOKEN}" \
  --max-jobs 1 \
  --poll-seconds 1 \
  --iterations 1000000 \
  --format human

wait_for_service_ready "${STATE_PATH}"

if [[ "${TRANSPORT}" == "http" ]]; then
  SUBMIT_TWO="$(curl -sS \
    -H "Authorization: Bearer ${SERVICE_TOKEN}" \
    -H 'Content-Type: application/json' \
    -X POST \
    --data "{\"request_id\":\"capability-service-2\",\"agent_id\":\"agent_allow\",\"org_id\":\"${ORG_ID}\",\"capability_name\":\"${CAPABILITY_NAME}\",\"payload_json\":{\"message\":\"${MESSAGE_TWO}\"},\"estimated_cost_usd\":0.05,\"kernel_path\":\"${FIXTURE_KERNEL}\"}" \
    "${HTTP_URL}/submit")"
else
  SUBMIT_TWO="$("${LOOM}" service submit \
    --root "${ROOT_DIR}" \
    --kernel-path "${FIXTURE_KERNEL}" \
    --service-token "${SERVICE_TOKEN}" \
    --agent-id agent_allow \
    --org-id "${ORG_ID}" \
    --capability "${CAPABILITY_NAME}" \
    --payload-json "{\"message\":\"${MESSAGE_TWO}\"}" \
    --estimated-cost-usd 0.05 \
    --format json)"
fi
printf '%s\n' "${SUBMIT_TWO}" >"${TMP_DIR}/submit-two.json"
JOB_TWO="$(read_json_field "${TMP_DIR}/submit-two.json" "job_id")"
if [[ -z "${JOB_TWO}" ]]; then
  echo "second service submit did not return job_id" >&2
  exit 1
fi
wait_for_completed_job "${JOB_TWO}" >"${TMP_DIR}/job-two.json"
JOB_TWO_PATH="$(read_json_field "${TMP_DIR}/job-two.json" "job_path")"
JOB_TWO_RESULT="$(dirname "${JOB_TWO_PATH}")/result.json"
assert_file_contains "${JOB_TWO_RESULT}" "\"capability_name\": \"${CAPABILITY_NAME}\""
assert_file_contains "${JOB_TWO_RESULT}" "${MESSAGE_TWO}"

"${LOOM}" logs --root "${ROOT_DIR}" --lines 20
"${LOOM}" stop --root "${ROOT_DIR}" --format human
"${LOOM}" stop --root "${ROOT_DIR}" --format human
"${LOOM}" status --root "${ROOT_DIR}"

echo "root=${ROOT_DIR}"
echo "transport=${TRANSPORT}"
echo "http_url=${HTTP_URL:-disabled}"
echo "capability=${CAPABILITY_NAME}"
echo "direct_worker_result=${DIRECT_RESULT_PATH}"
echo "job_one=${JOB_ONE}"
echo "job_two=${JOB_TWO}"
echo "logs=${ROOT_DIR}/logs"
echo "artifacts=${ROOT_DIR}/artifacts"
