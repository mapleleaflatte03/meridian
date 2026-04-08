#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
MERIDIAN_KERNEL_PATH="${MERIDIAN_KERNEL_PATH:-$MERIDIAN_ROOT/kernel}"
LOOM_ROOT="${LOOM_ROOT:-$MERIDIAN_ROOT/runtime/default}"
MERIDIAN_ORG_ID="${MERIDIAN_ORG_ID:-local_foundry}"
AGENT_NAME="${1:-My Assistant}"
RUN_NOW="${MERIDIAN_RUN_AGENT_NOW:-0}"
LOOM_BIN="${LOOM_BIN:-$MERIDIAN_ROOT/loom/target/release/loom}"

slugify() {
  local src="$1"
  src="$(echo "$src" | tr '[:upper:]' '[:lower:]')"
  src="$(echo "$src" | tr -cs 'a-z0-9' '-')"
  src="${src#-}"
  src="${src%-}"
  if [ -z "$src" ]; then
    src="my-assistant"
  fi
  echo "$src"
}

if [ ! -x "$LOOM_BIN" ]; then
  if command -v loom >/dev/null 2>&1; then
    LOOM_BIN="$(command -v loom)"
  else
    echo "[new-first-agent] Loom binary missing. Build first:"
    echo "  cd \"$MERIDIAN_ROOT/loom\" && cargo build -p meridian-loom --release"
    exit 1
  fi
fi

if [ ! -d "$MERIDIAN_KERNEL_PATH" ]; then
  echo "[new-first-agent] Missing kernel path: $MERIDIAN_KERNEL_PATH"
  exit 1
fi

echo "[new-first-agent] Initializing kernel state..."
(
  cd "$MERIDIAN_KERNEL_PATH"
  python3 quickstart.py --init-only >/tmp/meridian_new_first_agent_quickstart.log
)

mkdir -p "$LOOM_ROOT"
AGENT_SLUG="$(slugify "$AGENT_NAME")"

echo "[new-first-agent] Provisioning agent '$AGENT_NAME'..."
"$LOOM_BIN" new-agent \
  --name "$AGENT_NAME" \
  --root "$LOOM_ROOT" \
  --kernel-path "$MERIDIAN_KERNEL_PATH" \
  --org-id "$MERIDIAN_ORG_ID"

echo
echo "[new-first-agent] Agent ready."
echo "  slug: $AGENT_SLUG"
echo "  loom_root: $LOOM_ROOT"
echo "  kernel_path: $MERIDIAN_KERNEL_PATH"
echo "  org_id: $MERIDIAN_ORG_ID"

if [ "$RUN_NOW" = "1" ]; then
  echo "[new-first-agent] Starting run-agent loop..."
  "$LOOM_BIN" run-agent "$AGENT_SLUG"
else
  echo "Run now:"
  echo "  \"$LOOM_BIN\" run-agent \"$AGENT_SLUG\""
fi
