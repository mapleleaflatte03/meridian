#!/usr/bin/env bash
set -euo pipefail

# Meridian Loom // One-command embedded bootstrap
#
# Usage:
#   ./scripts/bootstrap_embedded.sh
#   LOOM=./target/release/loom ./scripts/bootstrap_embedded.sh
#   KERNEL_PATH=/path/to/kernel ./scripts/bootstrap_embedded.sh
#
# This script:
#   1. Checks for cargo/rustc
#   2. Builds the loom binary if not found
#   3. Initializes a standalone workspace
#   4. Runs doctor and health checks
#   5. Prints next steps

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOOM="${LOOM:-${REPO_ROOT}/target/release/loom}"
ROOT_DIR="${ROOT_DIR:-/tmp/loom-bootstrap}"
KERNEL_PATH="${KERNEL_PATH:-/opt/meridian-kernel}"
ORG_ID="${ORG_ID:-local_foundry}"

echo "=============================="
echo " Meridian Loom // BOOTSTRAP"
echo "=============================="
echo ""
echo "repo:        ${REPO_ROOT}"
echo "loom binary: ${LOOM}"
echo "root:        ${ROOT_DIR}"
echo "kernel:      ${KERNEL_PATH}"
echo "org_id:      ${ORG_ID}"
echo ""

# ---- Step 1: Check toolchain ----
echo "--- Step 1: Checking toolchain ---"

if ! command -v rustc &>/dev/null; then
  echo "FATAL: rustc not found."
  echo "Install Rust via: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  exit 1
fi
echo "rustc:  $(rustc --version)"

if ! command -v cargo &>/dev/null; then
  echo "FATAL: cargo not found."
  echo "Install Rust via: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  exit 1
fi
echo "cargo:  $(cargo --version)"
echo ""

# ---- Step 2: Build if needed ----
echo "--- Step 2: Build ---"

if [[ -x "${LOOM}" ]]; then
  echo "Binary already exists at ${LOOM}, skipping build."
else
  echo "Binary not found at ${LOOM}, building..."
  (cd "${REPO_ROOT}" && cargo build --release --workspace)
  echo "Build complete."
fi

if [[ ! -x "${LOOM}" ]]; then
  echo "FATAL: loom binary not found at ${LOOM} after build."
  exit 1
fi
echo ""

# ---- Step 3: Initialize workspace ----
echo "--- Step 3: Initialize workspace ---"

if [[ -d "${ROOT_DIR}" ]]; then
  echo "Removing previous workspace at ${ROOT_DIR}..."
  rm -rf "${ROOT_DIR}"
fi

INIT_ARGS=(--mode standalone --root "${ROOT_DIR}" --org-id "${ORG_ID}")
if [[ -d "${KERNEL_PATH}" ]]; then
  INIT_ARGS+=(--kernel-path "${KERNEL_PATH}")
  echo "Kernel found at ${KERNEL_PATH}, initializing in standalone mode."
else
  # Fall back to embedded mode when no kernel is present
  INIT_ARGS=(--mode embedded --root "${ROOT_DIR}" --org-id "${ORG_ID}")
  echo "No kernel at ${KERNEL_PATH}, initializing in embedded mode."
fi

"${LOOM}" init "${INIT_ARGS[@]}"
echo ""

# ---- Step 4: Doctor ----
echo "--- Step 4: Doctor ---"
"${LOOM}" doctor --root "${ROOT_DIR}" --format human
echo ""

# ---- Step 5: Health ----
echo "--- Step 5: Health ---"
"${LOOM}" health --root "${ROOT_DIR}" --format human
echo ""

# ---- What's next ----
echo "=============================="
echo " BOOTSTRAP COMPLETE"
echo "=============================="
echo ""
echo "Your Loom workspace is initialized at: ${ROOT_DIR}"
echo ""
echo "What's next:"
echo ""
echo "  1. First governed cell tutorial:"
echo "     Read docs/FIRST_GOVERNED_CELL.md for a walkthrough of creating"
echo "     your first governed action cell (envelope -> enqueue -> supervise -> inspect)."
echo ""
echo "     Or run it automatically:"
echo "       ./scripts/tests/rehearse_first_governed_cell.sh"
echo ""
echo "  2. Explore operator commands:"
echo "       ${LOOM} status --root ${ROOT_DIR}"
echo "       ${LOOM} config show --root ${ROOT_DIR}"
echo "       ${LOOM} contract show --root ${ROOT_DIR}"
echo ""
echo "  3. Try an operator profile:"
echo "       solo        -> profiles/solo.toml        single operator, minimal ceremony"
echo "       builder     -> profiles/builder.toml     active builder, wasm isolation available"
echo "       team        -> profiles/team.toml        approvals and parity for multi-operator work"
echo "       institution -> profiles/institution.toml full governance, microvm for sensitive actions"
echo "       Profiles are starting points, not maturity claims."
echo ""
echo "  4. Run the first governed cell:"
echo "       ./scripts/tests/rehearse_first_governed_cell.sh"
echo ""
echo "  5. Run the queue and denial rehearsals:"
echo "       ./scripts/tests/rehearse_supervisor_queue.sh"
echo "       ./scripts/tests/rehearse_local_sanction_preview.sh"
echo ""
echo "  6. Run the full rehearsal suite:"
echo "       ./scripts/tests/rehearse_setup.sh"
echo ""
