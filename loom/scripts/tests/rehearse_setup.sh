#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-/tmp/loom-rehearsal}"
KERNEL_PATH="${KERNEL_PATH:-/tmp/meridian-kernel}"

echo "== Meridian Loom rehearsal =="
echo "root:   ${ROOT_DIR}"
echo "kernel: ${KERNEL_PATH}"

rm -rf "${ROOT_DIR}"

LOOKUP_JSON="$(python3 "${KERNEL_PATH}/kernel/agent_registry.py" get --agent_id atlas)"
AGENT_ID="$(printf '%s\n' "${LOOKUP_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
AGENT_ORG_ID="$(printf '%s\n' "${LOOKUP_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["org_id"])')"

echo "agent:  ${AGENT_ID}"
echo "org:    ${AGENT_ORG_ID}"

cargo test --workspace
cargo build --workspace

./target/debug/loom init --mode embedded --kernel-path "${KERNEL_PATH}" --root "${ROOT_DIR}" --org-id "${AGENT_ORG_ID}"
./target/debug/loom doctor --root "${ROOT_DIR}" --format human
./target/debug/loom health --root "${ROOT_DIR}" --format human
./target/debug/loom status --root "${ROOT_DIR}"
./target/debug/loom config show --root "${ROOT_DIR}"
./target/debug/loom contract show --root "${ROOT_DIR}"
./target/debug/loom agent resolve --root "${ROOT_DIR}" --agent-id "${AGENT_ID}" --org-id "${AGENT_ORG_ID}" --format human
./target/debug/loom envelope build --root "${ROOT_DIR}" --agent-id "${AGENT_ID}" --org-id "${AGENT_ORG_ID}" --action-type research --resource web_search --estimated-cost-usd 0.05 --format human
./target/debug/loom capsule inspect --root "${ROOT_DIR}"
./target/debug/loom shadow preflight --root "${ROOT_DIR}" --agent-id "${AGENT_ID}" --org-id "${AGENT_ORG_ID}" --action-type research --resource web_search --estimated-cost-usd 0.05 --format human
./target/debug/loom shadow decide --root "${ROOT_DIR}" --agent-id "${AGENT_ID}" --org-id "${AGENT_ORG_ID}" --action-type research --resource web_search --estimated-cost-usd 0.05 --format human
set +e
./target/debug/loom shadow enforce --root "${ROOT_DIR}" --agent-id "${AGENT_ID}" --org-id "${AGENT_ORG_ID}" --action-type research --resource web_search --estimated-cost-usd 0.05 --format human
ENFORCE_CODE=$?
set -e
echo "shadow_enforce_exit_code: ${ENFORCE_CODE}"
if [[ "${ENFORCE_CODE}" -ne 2 ]]; then
  echo "expected shadow enforce to fail closed with exit code 2"
  exit 1
fi
set +e
./target/debug/loom action execute --root "${ROOT_DIR}" --agent-id "${AGENT_ID}" --org-id "${AGENT_ORG_ID}" --action-type research --resource web_search --estimated-cost-usd 0.05 --format human
EXECUTE_CODE=$?
set -e
echo "action_execute_exit_code: ${EXECUTE_CODE}"
if [[ "${EXECUTE_CODE}" -ne 2 ]]; then
  echo "expected action execute to fail closed with exit code 2"
  exit 1
fi
./target/debug/loom shadow compare --root "${ROOT_DIR}" --primary "${ROOT_DIR}/artifacts/shadow/reference_events.jsonl" --shadow "${ROOT_DIR}/artifacts/shadow/events.jsonl" --format human
./target/debug/loom shadow report --root "${ROOT_DIR}"
./target/debug/loom parity report --root "${ROOT_DIR}"

echo "== Rehearsal complete =="
