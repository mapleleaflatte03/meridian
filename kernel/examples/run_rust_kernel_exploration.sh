#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CRATE_DIR="${REPO_ROOT}/kernel-rs-explore"

if [[ ! -f "${CRATE_DIR}/Cargo.toml" ]]; then
  echo "missing crate at ${CRATE_DIR}" >&2
  exit 1
fi

echo "[kernel-rs-explore] running governance lane tests"
(cd "${CRATE_DIR}" && cargo test -- --nocapture)
echo "[kernel-rs-explore] PASS"

