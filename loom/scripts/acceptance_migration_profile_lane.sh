#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
KERNEL_PATH="${KERNEL_PATH:-/opt/meridian-kernel}"
LOOM_BIN="${LOOM_BIN:-${REPO_ROOT}/target/release/loom}"

echo "[migration-acceptance] building release binary"
(cd "${REPO_ROOT}" && cargo build -p meridian-loom --release >/dev/null)

run_profile() {
  local profile="$1"
  local expected_count="$2"
  local root="$3"
  echo "[migration-acceptance] profile=${profile} root=${root}"

  "${REPO_ROOT}/scripts/bootstrap_from_claw_profile.sh" \
    --profile "${profile}" \
    --root "${root}" \
    --kernel-path "${KERNEL_PATH}" \
    --org-id "migration_${profile}" \
    --charter "Migration ${profile} Charter" \
    --agent-name "Migration ${profile} Agent" \
    --loom-bin "${LOOM_BIN}"

  local registry="${root}/state/connect/registry.json"
  local latest="${root}/artifacts/connect/latest.json"
  test -f "${registry}" || { echo "missing registry: ${registry}" >&2; exit 1; }
  test -f "${latest}" || { echo "missing latest artifact: ${latest}" >&2; exit 1; }

  jq -e --argjson expected "${expected_count}" '.adapters | length >= $expected' "${registry}" >/dev/null
  jq -e '.adapters | all(.lifecycle.enabled == true)' "${registry}" >/dev/null
  jq -e '.status == "connect_scorecard"' "${latest}" >/dev/null
  jq -e --argjson expected "${expected_count}" '.adapters | length >= $expected' "${latest}" >/dev/null
  jq -e '.adapters | all(.security_posture_ok == true)' "${latest}" >/dev/null
  jq -e '.adapters | all(.tests_total >= 1)' "${latest}" >/dev/null
}

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "${TMP_ROOT}"' EXIT

run_profile openclaw 8 "${TMP_ROOT}/openclaw"
run_profile openfang 4 "${TMP_ROOT}/openfang"
run_profile zeroclaw 6 "${TMP_ROOT}/zeroclaw"

echo "[migration-acceptance] PASS profiles=openclaw,openfang,zeroclaw"
