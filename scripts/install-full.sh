#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${MERIDIAN_REPO_URL:-https://github.com/mapleleaflatte03/meridian.git}"
TARGET_DIR="${MERIDIAN_INSTALL_DIR:-$HOME/meridian}"
MERIDIAN_VERIFY_ONBOARDING="${MERIDIAN_VERIFY_ONBOARDING:-1}"
MERIDIAN_INSTALL_MODE="${MERIDIAN_INSTALL_MODE:-user}"

if [ -f "./scripts/bootstrap_full.sh" ] && [ -d "./loom" ] && [ -d "./kernel" ] && [ -d "./intelligence" ]; then
  echo "[install-full] Running from existing Meridian monorepo: $(pwd)"
  MERIDIAN_INSTALL_MODE="${MERIDIAN_INSTALL_MODE}" ./scripts/bootstrap_full.sh
  if [ "${MERIDIAN_VERIFY_ONBOARDING}" = "1" ]; then
    echo "[install-full] Verifying onboarding-ready contract..."
    ./scripts/acceptance_onboarding_ready_lane.sh
  fi
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

echo "[install-full] Running bootstrap (${MERIDIAN_INSTALL_MODE} mode)"
MERIDIAN_INSTALL_MODE="${MERIDIAN_INSTALL_MODE}" ./scripts/bootstrap_full.sh

if [ "${MERIDIAN_VERIFY_ONBOARDING}" = "1" ]; then
  echo "[install-full] Verifying onboarding-ready contract..."
  ./scripts/acceptance_onboarding_ready_lane.sh
fi

echo
echo "[install-full] Complete."
echo "Gateway smoke report: $TARGET_DIR/runtime/bootstrap_gateway_smoke.json"
if [ -f "$TARGET_DIR/runtime/bootstrap_gateway_smoke.json" ]; then
  python3 - "$TARGET_DIR/runtime/bootstrap_gateway_smoke.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
print("[install-full] Ready snapshot:")
print(f"  org_id: {payload.get('org_id')}")
print(f"  runtime_id: {payload.get('runtime_id')}")
print(f"  court_rules: {payload.get('court_rule_count')}")
print(f"  treasury_balance_usd: {payload.get('treasury_balance_usd')}")
print(f"  treasury_reserve_floor_usd: {payload.get('treasury_reserve_floor_usd')}")
PY
fi
echo "Install modes: user (default clean-slate), demo, maintainer"
echo "If needed: MERIDIAN_INSTALL_MODE=demo ./scripts/bootstrap_full.sh"
echo ""
echo "First-run onboarding: $TARGET_DIR/scripts/onboard.sh"
echo "Manual controls: ./scripts/dev-up.sh and ./scripts/dev-down.sh"
echo "Advanced: MERIDIAN_ORG_ID=<your-org-id> ./scripts/new-first-agent.sh \"My Assistant\""
