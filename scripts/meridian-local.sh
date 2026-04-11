#!/usr/bin/env bash
# meridian local — Start the Meridian workspace dashboard on localhost.
#
# Usage:
#   meridian local              # default port 18901
#   meridian local --port 8080  # custom port
#
# This starts the governed workspace server locally, serving both
# the dashboard HTML and the full JSON API surface.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONOREPO_ROOT="$(dirname "$SCRIPT_DIR")"
PLATFORM_DIR="$MONOREPO_ROOT/intelligence/company/meridian_platform"
WORKSPACE_PY="$PLATFORM_DIR/workspace.py"

if [ ! -f "$WORKSPACE_PY" ]; then
  echo "Error: workspace.py not found at $WORKSPACE_PY"
  echo "Run this script from the Meridian monorepo root."
  exit 1
fi

PORT="${1:-18901}"
# Allow --port N syntax
if [ "$PORT" = "--port" ] && [ -n "${2:-}" ]; then
  PORT="$2"
fi

echo "Starting Meridian local dashboard on http://localhost:$PORT"
echo "Press Ctrl+C to stop."
echo ""

cd "$PLATFORM_DIR"
exec python3 workspace.py --port "$PORT"
