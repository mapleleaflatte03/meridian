#!/usr/bin/env bash
# build-unified.sh — Build unified Meridian binary (Loom + Intelligence bridge).
#
# The unified deployment runs:
#   1. Loom runtime (Rust binary) — handles proof generation, PoGE, shadow logs
#   2. Intelligence workspace (Python) — serves dashboard, API, governance
#   3. Kernel (Python) — constitutional governance engine
#
# Architecture:
#   The Rust Loom binary runs as the primary process. It spawns the Python
#   Intelligence workspace as a managed subprocess. This gives single-binary
#   deployment feel while keeping Kernel in Python for flexibility.
#
# Usage:
#   ./build-unified.sh              # Build release binary
#   ./build-unified.sh --debug      # Build debug binary
#   ./build-unified.sh --check      # Check compilation only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONOREPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOOM_DIR="$MONOREPO_ROOT/loom"
INTELLIGENCE_DIR="$MONOREPO_ROOT/intelligence"
BUILD_MODE="release"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --debug) BUILD_MODE="debug"; shift ;;
    --check) BUILD_MODE="check"; shift ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

echo "=================================="
echo "  Meridian Unified Build"
echo "  Mode: $BUILD_MODE"
echo "=================================="
echo ""

# Step 1: Check Rust toolchain
if ! command -v cargo &>/dev/null; then
  echo "Error: Rust toolchain not found. Install via https://rustup.rs"
  exit 1
fi

echo "Step 1: Building Loom runtime..."
cd "$LOOM_DIR"

if [ "$BUILD_MODE" = "check" ]; then
  cargo check --workspace 2>&1
  echo "  Check passed."
elif [ "$BUILD_MODE" = "debug" ]; then
  cargo build --workspace 2>&1
  echo "  Debug build complete."
  BINARY_PATH="$LOOM_DIR/target/debug/loom-cli"
else
  cargo build --workspace --release 2>&1
  echo "  Release build complete."
  BINARY_PATH="$LOOM_DIR/target/release/loom-cli"
fi

echo ""

# Step 2: Verify Python deps for Intelligence + Kernel
echo "Step 2: Verifying Python environment..."
python3 -c "import json, os, sys; print('  Python ' + sys.version.split()[0] + ' OK')" 2>/dev/null || {
  echo "Error: Python 3 not found."
  exit 1
}
echo ""

# Step 3: Create unified launcher
echo "Step 3: Creating unified launcher..."
LAUNCHER="$MONOREPO_ROOT/meridian-server"
cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
# meridian-server — Unified Meridian server (Loom + Intelligence + Kernel)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOOM_BINARY="$SCRIPT_DIR/loom/target/release/loom-cli"
WORKSPACE_PY="$SCRIPT_DIR/intelligence/company/meridian_platform/workspace.py"
WORKSPACE_PORT="${MERIDIAN_PORT:-18901}"

# Use debug binary if release doesn't exist
if [ ! -f "$LOOM_BINARY" ]; then
  LOOM_BINARY="$SCRIPT_DIR/loom/target/debug/loom-cli"
fi

echo "Starting Meridian unified server..."

# Start Intelligence workspace
python3 "$WORKSPACE_PY" --port "$WORKSPACE_PORT" &
WS_PID=$!
echo "  Workspace: http://localhost:$WORKSPACE_PORT (PID: $WS_PID)"

# Start Loom runtime if binary exists
if [ -f "$LOOM_BINARY" ]; then
  "$LOOM_BINARY" serve &
  LOOM_PID=$!
  echo "  Loom runtime: PID $LOOM_PID"
else
  echo "  Loom binary not found, running workspace only."
  LOOM_PID=""
fi

# Trap cleanup
cleanup() {
  echo ""
  echo "Shutting down..."
  [ -n "$WS_PID" ] && kill "$WS_PID" 2>/dev/null || true
  [ -n "${LOOM_PID:-}" ] && kill "$LOOM_PID" 2>/dev/null || true
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

wait
LAUNCHER_EOF
chmod +x "$LAUNCHER"
echo "  Created: $LAUNCHER"
echo ""

if [ "$BUILD_MODE" != "check" ]; then
  echo "=================================="
  echo "  Build complete!"
  if [ -n "${BINARY_PATH:-}" ] && [ -f "${BINARY_PATH:-}" ]; then
    echo "  Loom binary: $BINARY_PATH"
    echo "  Size: $(du -sh "$BINARY_PATH" | cut -f1)"
  fi
  echo "  Unified launcher: $LAUNCHER"
  echo ""
  echo "  Run: ./meridian-server"
  echo "=================================="
fi
