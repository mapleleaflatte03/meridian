#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${MERIDIAN_REPO_URL:-https://github.com/mapleleaflatte03/meridian.git}"
TARGET_DIR="${MERIDIAN_INSTALL_DIR:-$HOME/meridian}"

if [ -f "./scripts/bootstrap_full.sh" ] && [ -d "./loom" ] && [ -d "./kernel" ] && [ -d "./intelligence" ]; then
  echo "[install-full] Running from existing Meridian monorepo: $(pwd)"
  ./scripts/bootstrap_full.sh
  exit 0
fi

if [ ! -d "$TARGET_DIR/.git" ]; then
  echo "[install-full] Cloning Meridian monorepo into $TARGET_DIR"
  git clone "$REPO_URL" "$TARGET_DIR"
else
  echo "[install-full] Reusing existing Meridian monorepo at $TARGET_DIR"
fi

cd "$TARGET_DIR"
echo "[install-full] Syncing latest main"
git fetch origin main --quiet
git checkout main --quiet
git pull --ff-only --quiet

echo "[install-full] Running bootstrap"
./scripts/bootstrap_full.sh

echo
echo "[install-full] Complete."
echo "Gateway smoke report: $TARGET_DIR/runtime/bootstrap_gateway_smoke.json"
echo "If needed: MERIDIAN_AUTO_START_STACK=0 ./scripts/bootstrap_full.sh"
echo "Manual controls: ./scripts/dev-up.sh and ./scripts/dev-down.sh"
