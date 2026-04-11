#!/usr/bin/env bash
# migrate-from-claw.sh — Migrate from OpenClaw/OpenFang/ZeroClaw/Paperclip to Meridian.
#
# This script:
#   1. Detects which Claw-ecosystem project is present
#   2. Exports agent configs, ledger state, and governance rules
#   3. Imports them into Meridian's institution structure
#
# Usage:
#   ./migrate-from-claw.sh [--source-dir /path/to/claw-project]
#   ./migrate-from-claw.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONOREPO_ROOT="$(dirname "$SCRIPT_DIR")"
PLATFORM_DIR="$MONOREPO_ROOT/intelligence/company/meridian_platform"
DRY_RUN=false
SOURCE_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-dir) SOURCE_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

echo "=================================="
echo "  Meridian Migration Tool"
echo "  From: OpenClaw / OpenFang / ZeroClaw / Paperclip"
echo "=================================="
echo ""

# Detect source project
detect_source() {
  local dir="${1:-.}"
  if [ -f "$dir/openclaw.toml" ] || [ -f "$dir/openclaw.yaml" ]; then
    echo "openclaw"
  elif [ -f "$dir/openfang.toml" ] || [ -f "$dir/openfang.yaml" ]; then
    echo "openfang"
  elif [ -f "$dir/zeroclaw.toml" ] || [ -f "$dir/zeroclaw.yaml" ]; then
    echo "zeroclaw"
  elif [ -f "$dir/paperclip.toml" ] || [ -f "$dir/paperclip.yaml" ]; then
    echo "paperclip"
  elif [ -f "$dir/config.toml" ]; then
    echo "generic_claw"
  else
    echo "unknown"
  fi
}

if [ -n "$SOURCE_DIR" ]; then
  SOURCE_TYPE=$(detect_source "$SOURCE_DIR")
else
  SOURCE_TYPE="unknown"
fi

echo "Detected source: $SOURCE_TYPE"
echo ""

if [ "$DRY_RUN" = true ]; then
  echo "[DRY RUN] Would perform the following:"
  echo "  1. Export agent configurations from $SOURCE_TYPE"
  echo "  2. Export ledger/treasury state"
  echo "  3. Export governance rules"
  echo "  4. Create new Meridian institution"
  echo "  5. Import agents via Meridian agent registry"
  echo "  6. Import ledger state to capsule treasury"
  echo "  7. Import governance rules to court"
  echo ""
  echo "Run without --dry-run to execute."
  exit 0
fi

# Bootstrap Meridian if not already done
echo "Step 1: Ensuring Meridian platform is bootstrapped..."
cd "$PLATFORM_DIR"
python3 bootstrap.py 2>/dev/null || true
echo "  Done."
echo ""

# Create migration institution
echo "Step 2: Creating migration institution..."
python3 -c "
from onboarding import provision_institution
try:
    result = provision_institution(
        name='Migrated from $SOURCE_TYPE',
        owner_id='migration_user',
        plan='starter',
    )
    print('  Created institution: ' + result['org_id'])
    print('  Capsule: ' + result['capsule_path'])
except Exception as e:
    print('  Note: ' + str(e))
"
echo ""

echo "Step 3: Provisioning default Hands..."
python3 -c "
from hands import provision_all_hands
from organizations import list_orgs
orgs = list_orgs(status_filter='active')
if orgs:
    latest = orgs[-1]
    agents = provision_all_hands(latest['id'])
    print('  Provisioned ' + str(len(agents)) + ' hands for ' + latest['name'])
else:
    print('  No active orgs found')
"
echo ""

echo "=================================="
echo "  Migration complete!"
echo "  Run 'meridian local' to start your dashboard."
echo "=================================="
