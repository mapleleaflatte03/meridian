#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/../fixture_kernel_local.sh"

LOOM="${LOOM:-${REPO_ROOT}/target/debug/loom}"
ROOT_DIR="${1:-/tmp/loom-clawskill-multi-import}"
FIXTURE_KERNEL="$(mktemp -d /tmp/loom-clawskill-multi-kernel.XXXXXX)"
BUNDLE_ROOT="$(mktemp -d /tmp/loom-clawskill-bundle.XXXXXX)"
SERVICE_TOKEN="${SERVICE_TOKEN:-loom-clawskill-multi-token}"
ORG_ID="${ORG_ID:-org_tutorial}"
WORKSPACE_SKILL_ROOT="${WORKSPACE_SKILL_ROOT:-/root/.openclaw/workspace/skills/malware-triage}"
BUNDLE_SOURCE_SKILL_ROOT="${BUNDLE_SOURCE_SKILL_ROOT:-/root/.openclaw/workspace/skills/safe-web-research}"
ARTIFACT_CAPABILITY="clawskill.malware-triage.v0"
BUNDLE_CAPABILITY="clawskill.safe-web-research-bundle.v0"

cleanup() {
  rm -rf "${FIXTURE_KERNEL}" "${BUNDLE_ROOT}" "${ROOT_DIR}"
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
    if not part:
        continue
    if isinstance(value, list):
        value = value[int(part)]
    else:
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

echo "== Meridian Loom // Multi-Shape Clawfamily Import =="
echo "root:               ${ROOT_DIR}"
echo "kernel:             ${FIXTURE_KERNEL}"
echo "workspace skill:    ${WORKSPACE_SKILL_ROOT}"
echo "bundle source root: ${BUNDLE_SOURCE_SKILL_ROOT}"
echo ""

ensure_debug_loom_binary "${REPO_ROOT}"
write_local_fixture_kernel "${FIXTURE_KERNEL}" "multi-shape clawfamily import"

mkdir -p "${BUNDLE_ROOT}/scripts"
cp "${BUNDLE_SOURCE_SKILL_ROOT}/scripts/fetch_safe.py" "${BUNDLE_ROOT}/scripts/fetch_safe.py"
cat > "${BUNDLE_ROOT}/clawskill.json" <<'EOF'
{
  "version": "clawfamily_skill_contract_v0",
  "name": "safe-web-research-bundle",
  "description": "Bundle manifest wrapper around the clawfamily safe web research script",
  "entry": "scripts/fetch_safe.py",
  "adapter_kind": "url_report_v0",
  "action_type": "skill_exec",
  "payload_mode": "json",
  "worker_kind": "python"
}
EOF

echo "--- Step 1: Initialize workspace ---"
"${LOOM}" init --mode embedded --root "${ROOT_DIR}" --kernel-path "${FIXTURE_KERNEL}" --org-id "${ORG_ID}"
echo ""

echo "--- Step 2: Import workspace skill shape ---"
"${LOOM}" capability import-workspace-skill \
  --root "${ROOT_DIR}" \
  --skill-root "${WORKSPACE_SKILL_ROOT}"
echo ""

echo "--- Step 3: Import bundle manifest shape ---"
"${LOOM}" capability import-workspace-skill \
  --root "${ROOT_DIR}" \
  --skill-root "${BUNDLE_ROOT}" \
  --name "${BUNDLE_CAPABILITY}"
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

echo "--- Step 4: Verify + promote imported capabilities ---"
"${LOOM}" capability verify \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --agent-id agent_tutorial \
  --org-id "${ORG_ID}" \
  --name "${ARTIFACT_CAPABILITY}" \
  --payload-json "{\"artifact_path\":\"${ARTIFACT_DIR}/suspicious.exe\",\"skip_container\":true}" \
  --estimated-cost-usd 0.05 \
  --expect-result-field skill_output.host_static.magic=pe \
  --expect-result-field skill_output.verdict.risk=high
"${LOOM}" capability promote --root "${ROOT_DIR}" --name "${ARTIFACT_CAPABILITY}"
echo ""

"${LOOM}" capability verify \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --agent-id agent_tutorial \
  --org-id "${ORG_ID}" \
  --name "${BUNDLE_CAPABILITY}" \
  --payload-json '{"url":"http://127.0.0.1/"}' \
  --estimated-cost-usd 0.05 \
  --expect-result-field skill_output.mode=safe-web-research \
  --expect-result-field skill_output.blocked.0.url=http://127.0.0.1/
"${LOOM}" capability promote --root "${ROOT_DIR}" --name "${BUNDLE_CAPABILITY}"
echo ""

echo "--- Step 5: Show imported capability contracts ---"
"${LOOM}" capability show --root "${ROOT_DIR}" --name "${ARTIFACT_CAPABILITY}"
echo ""
"${LOOM}" capability show --root "${ROOT_DIR}" --name "${BUNDLE_CAPABILITY}"
echo ""

echo "--- Step 6: Start service and submit both imported skills ---"
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

submit_capability() {
  local request_id="$1"
  local capability_name="$2"
  local payload_json="$3"
  if [[ -n "${HTTP_ADDRESS}" ]]; then
    curl -sS \
      -H "Authorization: Bearer ${SERVICE_TOKEN}" \
      -H 'Content-Type: application/json' \
      -X POST \
      --data "{\"request_id\":\"${request_id}\",\"agent_id\":\"agent_tutorial\",\"org_id\":\"${ORG_ID}\",\"capability_name\":\"${capability_name}\",\"payload_json\":${payload_json},\"estimated_cost_usd\":0.05,\"kernel_path\":\"${FIXTURE_KERNEL}\"}" \
      "http://${HTTP_ADDRESS}/submit"
  else
    "${LOOM}" service submit \
      --root "${ROOT_DIR}" \
      --kernel-path "${FIXTURE_KERNEL}" \
      --service-token "${SERVICE_TOKEN}" \
      --agent-id agent_tutorial \
      --org-id "${ORG_ID}" \
      --capability "${capability_name}" \
      --payload-json "${payload_json}" \
      --estimated-cost-usd 0.05 \
      --format json
  fi
}

ARTIFACT_SUBMIT="$(submit_capability "clawskill-artifact-service" "${ARTIFACT_CAPABILITY}" "{\"artifact_path\":\"${ARTIFACT_DIR}/suspicious.exe\",\"skip_container\":true}")"
printf '%s\n' "${ARTIFACT_SUBMIT}"
ARTIFACT_JOB_ID="$(read_json_field "${ARTIFACT_SUBMIT}" "job_id")"
ARTIFACT_JOB_JSON="$(wait_for_completed_job "${ARTIFACT_JOB_ID}")"
ARTIFACT_RESULT_PATH="$(python3 - <<'PY' "${ARTIFACT_JOB_JSON}"
import json, pathlib, sys
data = json.loads(sys.argv[1])
print(pathlib.Path(data["job_path"]).parent / "result.json")
PY
)"
python3 - <<'PY' "${ARTIFACT_RESULT_PATH}"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    data = json.load(handle)
assert data.get("capability_name") == "clawskill.malware-triage.v0"
assert ((data.get("skill_output") or {}).get("verdict") or {}).get("risk") == "high"
print(sys.argv[1])
PY
echo ""

BUNDLE_SUBMIT="$(submit_capability "clawskill-bundle-service" "${BUNDLE_CAPABILITY}" "{\"url\":\"http://127.0.0.1/\"}")"
printf '%s\n' "${BUNDLE_SUBMIT}"
BUNDLE_JOB_ID="$(read_json_field "${BUNDLE_SUBMIT}" "job_id")"
BUNDLE_JOB_JSON="$(wait_for_completed_job "${BUNDLE_JOB_ID}")"
BUNDLE_RESULT_PATH="$(python3 - <<'PY' "${BUNDLE_JOB_JSON}"
import json, pathlib, sys
data = json.loads(sys.argv[1])
print(pathlib.Path(data["job_path"]).parent / "result.json")
PY
)"
python3 - <<'PY' "${BUNDLE_RESULT_PATH}"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    data = json.load(handle)
assert data.get("capability_name") == "clawskill.safe-web-research-bundle.v0"
blocked = (data.get("skill_output") or {}).get("blocked") or []
assert blocked and blocked[0].get("url") == "http://127.0.0.1/"
print(sys.argv[1])
PY
echo ""

"${LOOM}" job inspect --root "${ROOT_DIR}" --job-id "${ARTIFACT_JOB_ID}" --format human
echo ""
"${LOOM}" job inspect --root "${ROOT_DIR}" --job-id "${BUNDLE_JOB_ID}" --format human
echo ""
"${LOOM}" logs --root "${ROOT_DIR}" --lines 20
echo ""

echo "--- Step 7: Stop service ---"
"${LOOM}" stop --root "${ROOT_DIR}" --format human
