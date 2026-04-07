#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGE="${PACKAGE:-meridian-loom}"
TEST_TARGET="${TEST_TARGET:-swarm_zk}"
TEST_NAME="${TEST_NAME:-swarm_run_settle_zk_one_command_lane}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --test-name)
      TEST_NAME="$2"
      shift 2
      ;;
    --test-target)
      TEST_TARGET="$2"
      shift 2
      ;;
    --package)
      PACKAGE="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

echo "[loom-acceptance] package=${PACKAGE} target=${TEST_TARGET} test=${TEST_NAME}"
(cd "${REPO_ROOT}" && cargo test -p "${PACKAGE}" --test "${TEST_TARGET}" "${TEST_NAME}" -- --nocapture)
echo "[loom-acceptance] PASS ${TEST_TARGET}::${TEST_NAME}"
