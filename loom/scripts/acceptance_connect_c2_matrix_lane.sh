#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "[loom-acceptance] C2 hardening matrix (rate-limit, malformed payload, reconnect storm, sanction path)"
(cd "${REPO_ROOT}" && cargo test -p meridian-loom --test connect connect_c2_hardening_matrix_enforces_rate_limit_malformed_and_sanction_path -- --nocapture)
echo "[loom-acceptance] PASS connect::c2_hardening_matrix"
