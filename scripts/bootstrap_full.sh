#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
export MERIDIAN_LOOM_ROOT="${MERIDIAN_LOOM_ROOT:-$MERIDIAN_ROOT/loom}"
export MERIDIAN_KERNEL_ROOT="${MERIDIAN_KERNEL_ROOT:-$MERIDIAN_ROOT/kernel}"
export MERIDIAN_INTELLIGENCE_ROOT="${MERIDIAN_INTELLIGENCE_ROOT:-$MERIDIAN_ROOT/intelligence}"
export MERIDIAN_ORG_ID="${MERIDIAN_ORG_ID:-local_foundry}"
export LOOM_RUNTIME_ROOT="${LOOM_RUNTIME_ROOT:-$MERIDIAN_ROOT/runtime/default}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing required command: $cmd" >&2
    exit 1
  fi
}

require_cmd python3
require_cmd cargo

echo "[bootstrap] Meridian root: $MERIDIAN_ROOT"
echo "[bootstrap] Initializing kernel state..."
(
  cd "$MERIDIAN_KERNEL_ROOT"
  python3 quickstart.py --init-only
)

echo "[bootstrap] Building Loom CLI..."
(
  cd "$MERIDIAN_LOOM_ROOT"
  cargo build -p meridian-loom --release
)

mkdir -p "$LOOM_RUNTIME_ROOT"

echo "[bootstrap] Bootstrap complete."
echo
echo "Next steps:"
echo "1) export MERIDIAN_ROOT=\"$MERIDIAN_ROOT\""
echo "2) Run gateway: cd \"$MERIDIAN_INTELLIGENCE_ROOT\" && python3 meridian_gateway.py"
echo "3) Loom binary: \"$MERIDIAN_LOOM_ROOT/target/release/loom\""
