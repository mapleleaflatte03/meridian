#!/usr/bin/env bash
set -euo pipefail

# ── Meridian First-Run Onboarding ──────────────────────────────────────────
#
# This is the authoritative path for creating your first local institution
# and first agent after a clean-slate install.
#
# Usage:
#   ./scripts/onboard.sh                   # interactive guided mode
#   ./scripts/onboard.sh --non-interactive # use defaults / env vars
#
# Environment overrides (for scripted / CI use):
#   MERIDIAN_INST_NAME        institution name         (default: prompt)
#   MERIDIAN_OWNER_ID         owner user id            (default: auto-generated)
#   MERIDIAN_INST_PLAN        plan tier                (default: free)
#   MERIDIAN_AGENT_NAME       first agent name         (default: prompt)
#   MERIDIAN_AGENT_ROLE       first agent role         (default: manager)
#   MERIDIAN_IMPORT_DEMO_PACK import demo data         (default: no)
#   MERIDIAN_ENABLE_GOVERNANCE enable governance gates  (default: yes)
#
# After onboarding, start the local stack:
#   ./scripts/dev-up.sh
# ──────────────────────────────────────────────────────────────────────────

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
PLATFORM_DIR="${MERIDIAN_ROOT}/intelligence/company/meridian_platform"
LOOM_BIN="${LOOM_BIN:-$MERIDIAN_ROOT/loom/target/release/loom}"
KERNEL_PATH="${MERIDIAN_ROOT}/kernel"

NON_INTERACTIVE=0
for arg in "$@"; do
  case "$arg" in
    --non-interactive) NON_INTERACTIVE=1 ;;
  esac
done

prompt_or_default() {
  local var_name="$1"
  local prompt_text="$2"
  local default_value="$3"
  local current_value="${!var_name:-}"

  if [ -n "$current_value" ]; then
    echo "$current_value"
    return
  fi

  if [ "$NON_INTERACTIVE" = "1" ]; then
    echo "$default_value"
    return
  fi

  local input=""
  read -rp "$prompt_text [$default_value]: " input
  echo "${input:-$default_value}"
}

generate_owner_id() {
  echo "user_$(head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n')"
}

echo ""
echo "================================================================"
echo "  Meridian — First-Run Onboarding"
echo "================================================================"
echo ""
echo "  This guided flow creates your first local institution and"
echo "  first agent. Everything stays on your machine."
echo ""
echo "  What this creates:"
echo "    - your own institution (organization + capsule + treasury)"
echo "    - your own first agent (registered in your institution)"
echo "    - local workspace config bound to your institution"
echo ""
echo "  What this does NOT do:"
echo "    - upload anything to a remote service"
echo "    - create accounts on app.welliam.codes or any external site"
echo "    - import demo/maintainer data (unless you choose to)"
echo ""
echo "----------------------------------------------------------------"

# ── Collect inputs ──────────────────────────────────────────────────────

INST_NAME="$(prompt_or_default MERIDIAN_INST_NAME "Institution name" "My Workspace")"
OWNER_ID="${MERIDIAN_OWNER_ID:-$(generate_owner_id)}"
INST_PLAN="$(prompt_or_default MERIDIAN_INST_PLAN "Plan (free / starter / pro / enterprise)" "free")"

AGENT_NAME="$(prompt_or_default MERIDIAN_AGENT_NAME "First agent name" "Assistant")"
AGENT_ROLE="$(prompt_or_default MERIDIAN_AGENT_ROLE "First agent role (manager / analyst / executor / writer)" "manager")"

IMPORT_DEMO="$(prompt_or_default MERIDIAN_IMPORT_DEMO_PACK "Import demo data pack? (yes / no)" "no")"
ENABLE_GOV="$(prompt_or_default MERIDIAN_ENABLE_GOVERNANCE "Enable governance gates? (yes / no)" "yes")"

echo ""
echo "----------------------------------------------------------------"
echo "  Summary"
echo "----------------------------------------------------------------"
echo "  Institution:   $INST_NAME"
echo "  Owner ID:      $OWNER_ID"
echo "  Plan:          $INST_PLAN"
echo "  First agent:   $AGENT_NAME (role: $AGENT_ROLE)"
echo "  Demo pack:     $IMPORT_DEMO"
echo "  Governance:    $ENABLE_GOV"
echo "  Data root:     $MERIDIAN_ROOT/runtime"
echo "  Config root:   $MERIDIAN_ROOT/intelligence"
echo "----------------------------------------------------------------"

if [ "$NON_INTERACTIVE" = "0" ]; then
  read -rp "Proceed? (y/n): " confirm
  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "[onboard] Cancelled."
    exit 0
  fi
fi

echo ""
echo "[onboard] Creating institution..."

# ── Provision institution via onboarding.py ─────────────────────────────

ONBOARD_RESULT="$(cd "$PLATFORM_DIR" && python3 - "$INST_NAME" "$OWNER_ID" "$INST_PLAN" <<'PY'
import sys
import json
sys.path.insert(0, '.')
from onboarding import provision_institution

name = sys.argv[1]
owner_id = sys.argv[2]
plan = sys.argv[3]

result = provision_institution(name, owner_id, plan)
print(json.dumps({
    'org_id': result['org_id'],
    'org_name': result['org'].get('name', ''),
    'org_slug': result['org'].get('slug', ''),
    'owner_id': owner_id,
    'plan': plan,
    'capsule_path': result['capsule_path'],
    'treasury_ledger': result['treasury']['ledger'],
}))
PY
)"

ORG_ID="$(echo "$ONBOARD_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['org_id'])")"
ORG_SLUG="$(echo "$ONBOARD_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['org_slug'])")"

echo "[onboard] Institution created."
echo "  org_id:  $ORG_ID"
echo "  slug:    $ORG_SLUG"
echo "  plan:    $INST_PLAN"
echo "  owner:   $OWNER_ID"

# ── Write local onboarding state ────────────────────────────────────────

ONBOARD_STATE_DIR="${MERIDIAN_ROOT}/runtime"
mkdir -p "$ONBOARD_STATE_DIR"

echo "$ONBOARD_RESULT" | python3 -c "
import sys, json
result = json.load(sys.stdin)
state = {
    'org_id': result['org_id'],
    'org_slug': result.get('org_slug', ''),
    'owner_id': result['owner_id'],
    'plan': result['plan'],
    'onboarded_at': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    'source': 'onboard.sh',
}
with open('$ONBOARD_STATE_DIR/onboard_state.json', 'w') as f:
    json.dump(state, f, indent=2)
print(json.dumps(state, indent=2))
" > /dev/null

echo "[onboard] Onboarding state saved to: $ONBOARD_STATE_DIR/onboard_state.json"

# ── Create first agent ──────────────────────────────────────────────────

echo ""
echo "[onboard] Provisioning first agent..."

if [ ! -x "$LOOM_BIN" ]; then
  if command -v loom >/dev/null 2>&1; then
    LOOM_BIN="$(command -v loom)"
  else
    echo "[onboard] Warning: Loom binary not found. Skipping agent provisioning."
    echo "[onboard] Build Loom first: cd \"$MERIDIAN_ROOT/loom\" && cargo build -p meridian-loom --release"
    echo "[onboard] Then create your agent:"
    echo "  MERIDIAN_ORG_ID=$ORG_ID ./scripts/new-first-agent.sh \"$AGENT_NAME\""
    LOOM_BIN=""
  fi
fi

AGENT_CREATED=0
if [ -n "$LOOM_BIN" ]; then
  LOOM_ROOT="${MERIDIAN_ROOT}/runtime/default"
  mkdir -p "$LOOM_ROOT"

  AGENT_SLUG="$(echo "$AGENT_NAME" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//')"
  if [ -z "$AGENT_SLUG" ]; then
    AGENT_SLUG="assistant"
  fi

  "$LOOM_BIN" new-agent \
    --name "$AGENT_NAME" \
    --root "$LOOM_ROOT" \
    --kernel-path "$KERNEL_PATH" \
    --org-id "$ORG_ID" && AGENT_CREATED=1 || true

  if [ "$AGENT_CREATED" = "1" ]; then
    echo "[onboard] Agent created."
    echo "  name:    $AGENT_NAME"
    echo "  slug:    $AGENT_SLUG"
    echo "  org_id:  $ORG_ID"
    echo "  role:    $AGENT_ROLE"
  else
    echo "[onboard] Warning: Agent provisioning failed. Create manually:"
    echo "  MERIDIAN_ORG_ID=$ORG_ID ./scripts/new-first-agent.sh \"$AGENT_NAME\""
  fi
fi

# ── Demo pack import ────────────────────────────────────────────────────

if [ "$IMPORT_DEMO" = "yes" ]; then
  echo ""
  echo "[onboard] Demo pack import is not yet available."
  echo "  Use MERIDIAN_INSTALL_MODE=demo ./scripts/bootstrap_full.sh for demo-seeded state."
fi

# ── Final summary ───────────────────────────────────────────────────────

echo ""
echo "================================================================"
echo "  Onboarding Complete"
echo "================================================================"
echo ""
echo "  Your institution:"
echo "    name:     $INST_NAME"
echo "    org_id:   $ORG_ID"
echo "    slug:     $ORG_SLUG"
echo "    owner:    $OWNER_ID"
echo "    plan:     $INST_PLAN"
echo ""
if [ "$AGENT_CREATED" = "1" ]; then
  echo "  Your first agent:"
  echo "    name:     $AGENT_NAME"
  echo "    slug:     $AGENT_SLUG"
  echo "    org_id:   $ORG_ID"
  echo ""
fi
echo "  What is local (your machine only):"
echo "    - Institution data:  $MERIDIAN_ROOT/intelligence/"
echo "    - Runtime state:     $MERIDIAN_ROOT/runtime/"
echo "    - Kernel governance: $MERIDIAN_ROOT/kernel/"
echo "    - Loom agents:       $MERIDIAN_ROOT/runtime/default/"
echo ""
echo "  What is the public demo site:"
echo "    - https://app.welliam.codes is a public showcase."
echo "    - It is NOT your personal dashboard."
echo "    - Your local workspace runs on localhost after dev-up."
echo ""
echo "  What requires sign-in:"
echo "    - The local workspace API requires credentials after dev-up."
echo "    - The trust-ops page on the public site requires separate auth."
echo ""
echo "  Next steps:"
echo "    1) Start your local stack:"
echo "       MERIDIAN_ORG_ID=$ORG_ID MERIDIAN_WORKSPACE_ORG_ID=$ORG_ID ./scripts/dev-up.sh"
echo ""
echo "    2) Access your local workspace:"
echo "       http://127.0.0.1:8266/api/status"
echo ""
if [ "$AGENT_CREATED" = "1" ]; then
  echo "    3) Run your agent:"
  echo "       \"$LOOM_BIN\" run-agent \"$AGENT_SLUG\""
  echo ""
fi
echo "    Your onboarding state: $ONBOARD_STATE_DIR/onboard_state.json"
echo ""
