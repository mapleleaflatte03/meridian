#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGE="${PACKAGE:-meridian-loom}"
TEST_TARGET="${TEST_TARGET:-extension}"
TEST_NAME="${TEST_NAME:-}"

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

if [[ -n "${TEST_NAME}" ]]; then
  echo "[loom-acceptance] package=${PACKAGE} target=${TEST_TARGET} test=${TEST_NAME}"
  (cd "${REPO_ROOT}" && cargo test -p "${PACKAGE}" --test "${TEST_TARGET}" "${TEST_NAME}" -- --nocapture)
  echo "[loom-acceptance] PASS ${TEST_TARGET}::${TEST_NAME}"
else
  echo "[loom-acceptance] package=${PACKAGE} target=${TEST_TARGET}"
  (cd "${REPO_ROOT}" && cargo test -p "${PACKAGE}" --test "${TEST_TARGET}" -- --nocapture)
  echo "[loom-acceptance] PASS ${TEST_TARGET}"
fi
