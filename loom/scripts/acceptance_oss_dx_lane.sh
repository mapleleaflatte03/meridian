#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

required_files=(
  "README.md"
  "CONTRIBUTING.md"
  "docs/ARCHITECTURE.md"
  "docs/COMMUNITY_MAP.md"
  ".github/ISSUE_TEMPLATE/bug_report.md"
  ".github/ISSUE_TEMPLATE/feature_request.md"
  ".github/pull_request_template.md"
  "scripts/dev_first_proof.sh"
)

echo "[oss-dx] validating required contributor assets"
for rel in "${required_files[@]}"; do
  if [[ ! -f "${REPO_ROOT}/${rel}" ]]; then
    echo "[oss-dx] missing required file: ${rel}" >&2
    exit 1
  fi
done

echo "[oss-dx] checking shell script syntax"
bash -n "${REPO_ROOT}/scripts/dev_first_proof.sh"

echo "[oss-dx] smoke test quickstart lane contract"
(cd "${REPO_ROOT}" && cargo test -p meridian-loom --test quickstart -- --nocapture)

echo "[oss-dx] PASS acceptance_oss_dx_lane"
