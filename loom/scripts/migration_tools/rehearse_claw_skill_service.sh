#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/../fixture_kernel_local.sh"

LOOM="${LOOM:-${REPO_ROOT}/target/debug/loom}"
ROOT_DIR="${1:-/tmp/loom-clawskill-service}"
FIXTURE_KERNEL="$(mktemp -d /tmp/loom-clawskill-service-kernel.XXXXXX)"
SERVICE_TOKEN="${SERVICE_TOKEN:-loom-clawskill-service-token}"
ORG_ID="${ORG_ID:-org_tutorial}"
SKILL_ROOT="${SKILL_ROOT:-/root/.openclaw/workspace/skills/malware-triage}"
CAPABILITY_NAME="clawskill.malware-triage.v0"

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

export LOOM_SERVICE_TOKEN="${SERVICE_TOKEN}"
export MERIDIAN_OPENCLAW_PROOF_SCRIPT="${FIXTURE_KERNEL}/kernel/missing_openclaw_runtime_proof.py"

echo "== Meridian Loom // Clawfamily Skill Service Rehearsal =="
echo "root:   ${ROOT_DIR}"
echo "kernel: ${FIXTURE_KERNEL}"
echo "skill:  ${SKILL_ROOT}"
echo ""

ensure_debug_loom_binary "${REPO_ROOT}"
write_local_fixture_kernel "${FIXTURE_KERNEL}" "clawfamily skill service rehearsal"

echo "--- Step 1: Initialize workspace ---"
"${LOOM}" init --mode embedded --root "${ROOT_DIR}" --kernel-path "${FIXTURE_KERNEL}" --org-id "${ORG_ID}"
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

echo "--- Step 3: Verify + promote imported capability ---"
"${LOOM}" capability verify \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --agent-id agent_tutorial \
  --org-id "${ORG_ID}" \
  --name "${CAPABILITY_NAME}" \
  --payload-json "{\"artifact_path\":\"${ARTIFACT_DIR}/suspicious.exe\",\"skip_container\":true}" \
  --estimated-cost-usd 0.05 \
  --expect-result-field skill_output.host_static.magic=pe \
  --expect-result-field skill_output.verdict.risk=high
echo ""
"${LOOM}" capability promote --root "${ROOT_DIR}" --name "${CAPABILITY_NAME}"
echo ""

echo "--- Step 4: Show imported capability contract ---"
"${LOOM}" capability show --root "${ROOT_DIR}" --name "${CAPABILITY_NAME}"
echo ""

echo "--- Step 5: Start service and submit imported skill ---"
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

if [[ -n "${HTTP_ADDRESS}" ]]; then
  SUBMIT_JSON="$(curl -sS \
    -H "Authorization: Bearer ${SERVICE_TOKEN}" \
    -H 'Content-Type: application/json' \
    -X POST \
    --data "{\"request_id\":\"claw-skill-service\",\"agent_id\":\"agent_tutorial\",\"org_id\":\"${ORG_ID}\",\"capability_name\":\"${CAPABILITY_NAME}\",\"payload_json\":{\"artifact_path\":\"${ARTIFACT_DIR}/suspicious.exe\",\"skip_container\":true},\"estimated_cost_usd\":0.05,\"kernel_path\":\"${FIXTURE_KERNEL}\"}" \
    "http://${HTTP_ADDRESS}/submit")"
else
  SUBMIT_JSON="$("${LOOM}" service submit \
    --root "${ROOT_DIR}" \
    --kernel-path "${FIXTURE_KERNEL}" \
    --service-token "${SERVICE_TOKEN}" \
    --agent-id agent_tutorial \
    --org-id "${ORG_ID}" \
    --capability "${CAPABILITY_NAME}" \
    --payload-json "{\"artifact_path\":\"${ARTIFACT_DIR}/suspicious.exe\",\"skip_container\":true}" \
    --estimated-cost-usd 0.05 \
    --format json)"
fi
printf '%s\n' "${SUBMIT_JSON}"
echo ""

JOB_ID="$(read_json_field "${SUBMIT_JSON}" "job_id")"
JOB_JSON="$(wait_for_completed_job "${JOB_ID}")"

RESULT_PATH="$(python3 - <<'PY' "${JOB_JSON}"
import json, pathlib, sys
data = json.loads(sys.argv[1])
job_path = pathlib.Path(data["job_path"])
print(job_path.parent / "result.json")
PY
)"
python3 - <<'PY' "${RESULT_PATH}"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    data = json.load(handle)
assert data.get("capability_name") == "clawskill.malware-triage.v0"
assert ((data.get("skill_output") or {}).get("verdict") or {}).get("risk") == "high"
print(sys.argv[1])
PY

"${LOOM}" job inspect --root "${ROOT_DIR}" --job-id "${JOB_ID}" --format human
"${LOOM}" logs --root "${ROOT_DIR}" --lines 20
echo ""

echo "--- Step 6: Stop service ---"
"${LOOM}" stop --root "${ROOT_DIR}" --format human
