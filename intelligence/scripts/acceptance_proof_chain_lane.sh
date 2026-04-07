#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[meridian-acceptance] proof_chain_lane"
cd "${WORKSPACE_ROOT}"
"${PYTHON_BIN}" -m unittest \
  company.meridian_platform.test_loom_runtime_proof.LoomRuntimeProofTests.test_runtime_proof_contract_fields_are_non_null \
  company.meridian_platform.test_workspace_context.LiveWorkspaceContextTests.test_api_status_exposes_runtime_core
echo "[meridian-acceptance] PASS proof_chain_lane"
