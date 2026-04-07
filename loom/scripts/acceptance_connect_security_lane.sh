#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGE="${PACKAGE:-meridian-loom}"
TEST_TARGET="${TEST_TARGET:-connect}"
TEST_NAME="${TEST_NAME:-connect_scorecard_fix_applies_security_baseline_for_priority_transports}"

echo "[loom-acceptance] package=${PACKAGE} target=${TEST_TARGET} test=${TEST_NAME}"
(cd "${REPO_ROOT}" && cargo test -p "${PACKAGE}" --test "${TEST_TARGET}" "${TEST_NAME}" -- --nocapture)
echo "[loom-acceptance] PASS ${TEST_TARGET}::${TEST_NAME}"
