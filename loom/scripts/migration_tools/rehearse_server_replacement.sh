#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/../fixture_kernel_local.sh"

LOOM="${LOOM:-${REPO_ROOT}/target/debug/loom}"
ROOT_DIR="${1:-/tmp/loom-server-replacement}"
FIXTURE_KERNEL="$(mktemp -d /tmp/loom-server-replacement-kernel.XXXXXX)"
SERVICE_TOKEN="${SERVICE_TOKEN:-loom-server-replacement-token}"
ORG_ID="${ORG_ID:-local_foundry}"
SKILL_ROOT="${SKILL_ROOT:-/root/.openclaw/workspace/skills/malware-triage}"
CAPABILITY_NAME="${CAPABILITY_NAME:-clawskill.malware-triage.v0}"

cleanup() {
  rm -rf "${FIXTURE_KERNEL}" "${ROOT_DIR}"
}
trap cleanup EXIT

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

read_json_field() {
  python3 - <<'PY' "$1" "$2"
import json, sys
value = json.loads(sys.argv[1])
for part in sys.argv[2].split('.'):
    if part:
        value = value.get(part) if isinstance(value, dict) else None
print("" if value is None else value)
PY
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

assert_imported_skill_ready() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "replacement rehearsal requires python3 for imported clawfamily skills" >&2
    exit 1
  fi
  if [[ ! -f "${SKILL_ROOT}/SKILL.md" ]]; then
    echo "replacement rehearsal skill root missing SKILL.md: ${SKILL_ROOT}" >&2
    exit 1
  fi
  if [[ ! -d "${SKILL_ROOT}/scripts" ]]; then
    echo "replacement rehearsal skill root missing scripts/: ${SKILL_ROOT}" >&2
    exit 1
  fi
}

assert_result_is_high_risk() {
  local result_path="$1"
  python3 - <<'PY' "${result_path}" "${CAPABILITY_NAME}"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    data = json.load(handle)
assert data.get("capability_name") == sys.argv[2]
assert ((data.get("skill_output") or {}).get("verdict") or {}).get("risk") == "high"
print(sys.argv[1])
PY
}

result_path_for_job_json() {
  python3 - <<'PY' "$1"
import json, pathlib, sys
data = json.loads(sys.argv[1])
print(pathlib.Path(data["job_path"]).parent / "result.json")
PY
}

submit_imported_skill() {
  local request_id="$1"
  local artifact_path="$2"
  if [[ -n "${HTTP_ADDRESS}" ]]; then
    curl -sS \
      -H "Authorization: Bearer ${SERVICE_TOKEN}" \
      -H 'Content-Type: application/json' \
      -X POST \
      --data "{\"request_id\":\"${request_id}\",\"agent_id\":\"agent_allow\",\"org_id\":\"${ORG_ID}\",\"capability_name\":\"${CAPABILITY_NAME}\",\"payload_json\":{\"artifact_path\":\"${artifact_path}\",\"skip_container\":true},\"estimated_cost_usd\":0.05,\"kernel_path\":\"${FIXTURE_KERNEL}\"}" \
      "http://${HTTP_ADDRESS}/submit"
  else
    "${LOOM}" service submit \
      --root "${ROOT_DIR}" \
      --kernel-path "${FIXTURE_KERNEL}" \
      --service-token "${SERVICE_TOKEN}" \
      --agent-id agent_allow \
      --org-id "${ORG_ID}" \
      --capability "${CAPABILITY_NAME}" \
      --payload-json "{\"artifact_path\":\"${artifact_path}\",\"skip_container\":true}" \
      --estimated-cost-usd 0.05 \
      --format json
  fi
}

export LOOM_SERVICE_TOKEN="${SERVICE_TOKEN}"
export MERIDIAN_OPENCLAW_PROOF_SCRIPT="${FIXTURE_KERNEL}/kernel/missing_openclaw_runtime_proof.py"

echo "== Meridian Loom // Server Replacement Rehearsal =="
echo "root:   ${ROOT_DIR}"
echo "kernel: ${FIXTURE_KERNEL}"
echo "skill:  ${SKILL_ROOT}"
echo "cap:    ${CAPABILITY_NAME}"
echo "agent:  agent_allow"
echo "org:    ${ORG_ID}"
echo ""

ensure_debug_loom_binary "${REPO_ROOT}"
write_local_fixture_kernel "${FIXTURE_KERNEL}" "server replacement rehearsal"
assert_imported_skill_ready

echo "--- Step 1: Initialize local runtime root ---"
"${LOOM}" init --mode embedded --root "${ROOT_DIR}" --kernel-path "${FIXTURE_KERNEL}" --org-id "${ORG_ID}"
echo ""

echo "--- Step 2: Import clawfamily skill and prepare local sample artifacts ---"
"${LOOM}" capability import-workspace-skill \
  --root "${ROOT_DIR}" \
  --skill-root "${SKILL_ROOT}"
echo ""

ARTIFACT_DIR="${ROOT_DIR}/samples"
mkdir -p "${ARTIFACT_DIR}"
python3 - <<'PY' "${ARTIFACT_DIR}/suspicious-a.exe" "${ARTIFACT_DIR}/suspicious-b.exe"
from pathlib import Path
import sys
for raw in sys.argv[1:]:
    path = Path(raw)
    path.write_bytes(b"MZ" + b"\x90" * 256)
    print(path)
PY
echo ""

echo "--- Step 3: Verify and promote imported replacement skill ---"
"${LOOM}" capability verify \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --agent-id agent_allow \
  --org-id "${ORG_ID}" \
  --name "${CAPABILITY_NAME}" \
  --payload-json "{\"artifact_path\":\"${ARTIFACT_DIR}/suspicious-a.exe\",\"skip_container\":true}" \
  --estimated-cost-usd 0.05 \
  --expect-result-field skill_output.host_static.magic=pe \
  --expect-result-field skill_output.verdict.risk=high
echo ""
"${LOOM}" capability promote --root "${ROOT_DIR}" --name "${CAPABILITY_NAME}"
echo ""
"${LOOM}" capability show --root "${ROOT_DIR}" --name "${CAPABILITY_NAME}"
echo ""

echo "--- Step 4: Start Loom as the local service ---"
"${LOOM}" start \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --http-address 127.0.0.1:0 \
  --service-token "${SERVICE_TOKEN}" \
  --max-jobs 1 \
  --poll-seconds 1 \
  --iterations 1000000 \
  --format human
echo ""

STATE_PATH="${ROOT_DIR}/run/service/runtime_state.json"
wait_for_service_ready "${STATE_PATH}"
HTTP_ADDRESS="$(python3 - <<'PY' "${STATE_PATH}"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    data = json.load(handle)
print(data.get("http_address") or "")
PY
)"

echo "--- Step 5: Submit imported clawfamily skill through Loom service ---"
SUBMIT_ONE="$(submit_imported_skill "server-replacement-1" "${ARTIFACT_DIR}/suspicious-a.exe")"
printf '%s\n' "${SUBMIT_ONE}"
echo ""

JOB_ONE_ID="$(read_json_field "${SUBMIT_ONE}" "job_id")"
JOB_ONE_JSON="$(wait_for_completed_job "${JOB_ONE_ID}")"
RESULT_ONE_PATH="$(result_path_for_job_json "${JOB_ONE_JSON}")"
assert_result_is_high_risk "${RESULT_ONE_PATH}"
"${LOOM}" job inspect --root "${ROOT_DIR}" --job-id "${JOB_ONE_ID}" --format human
echo ""

echo "--- Step 6: Restart service and resubmit the same imported skill ---"
"${LOOM}" restart \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --http-address "${HTTP_ADDRESS:-127.0.0.1:0}" \
  --service-token "${SERVICE_TOKEN}" \
  --max-jobs 1 \
  --poll-seconds 1 \
  --iterations 1000000 \
  --format human
echo ""

wait_for_service_ready "${STATE_PATH}"

SUBMIT_TWO="$(submit_imported_skill "server-replacement-2" "${ARTIFACT_DIR}/suspicious-b.exe")"
printf '%s\n' "${SUBMIT_TWO}"
echo ""

JOB_TWO_ID="$(read_json_field "${SUBMIT_TWO}" "job_id")"
JOB_TWO_JSON="$(wait_for_completed_job "${JOB_TWO_ID}")"
RESULT_TWO_PATH="$(result_path_for_job_json "${JOB_TWO_JSON}")"
assert_result_is_high_risk "${RESULT_TWO_PATH}"
"${LOOM}" job inspect --root "${ROOT_DIR}" --job-id "${JOB_TWO_ID}" --format human
echo ""

echo "--- Step 7: Operator surfaces ---"
"${LOOM}" status --root "${ROOT_DIR}"
"${LOOM}" logs --root "${ROOT_DIR}" --lines 20
echo ""

echo "--- Step 8: Stop cleanly ---"
"${LOOM}" stop --root "${ROOT_DIR}" --format human
"${LOOM}" stop --root "${ROOT_DIR}" --format human
