#!/usr/bin/env bash
set -euo pipefail

# ── Meridian First-Run Onboarding ──────────────────────────────────────────
#
# One product. One install. Choose your mode in this script.
#
# Usage:
#   ./scripts/onboard.sh                    # interactive guided mode
#   ./scripts/onboard.sh --mode core        # Core: quick daily-use setup
#   ./scripts/onboard.sh --mode team        # Team: Core + governance depth
#   ./scripts/onboard.sh --non-interactive  # use env var defaults
#
# Mode selection:
#   Meridian Core  — daily-use local agent runtime (browser, research, memory,
#                    scheduling, agent loops). No governance expertise required.
#   Meridian Team  — Core plus governance depth (institution treasury, court
#                    rules, warrants, authority gates, audit surfaces).
#
# Environment overrides (for scripted / CI use):
#   MERIDIAN_MODE             mode: core | team          (default: interactive prompt)
#   MERIDIAN_INST_NAME        institution name           (default: prompt)
#   MERIDIAN_OWNER_ID         owner user id              (default: auto-generated)
#   MERIDIAN_AGENT_NAME       first agent name           (default: prompt)
#   MERIDIAN_AGENT_ROLE       first agent role label     (default: manager_tech_lead)
#   MERIDIAN_TEAM_PRESET      team preset                (default: dev_team)
#   MERIDIAN_IMPORT_DEMO_PACK import demo data           (default: no)
#   MERIDIAN_ENABLE_GOVERNANCE enable governance gates   (default: yes)
#   MERIDIAN_BRAIN_ROUTE_TYPE execution route type       (default: cli_session)
#   MERIDIAN_BRAIN_CLI_BIN    cli provider binary        (default: claude)
#   MERIDIAN_BRAIN_PROVIDER_PROFILE provider profile     (default: claude_local)
#   MERIDIAN_BRAIN_MODEL      execution model            (default: empty)
#   MERIDIAN_BRAIN_AUTH_PROFILE auth profile name        (default: provider profile)
#   MERIDIAN_BRAIN_CLI_HOME   cli auth home              (default: empty)
#   MERIDIAN_BRAIN_ENDPOINT   http provider endpoint     (default: empty)
#   MERIDIAN_BRAIN_AUTH_ENV   http auth env var name     (default: empty)
#   MERIDIAN_BRAIN_KEY_ENV_POOL comma-separated auth env fallbacks
# ──────────────────────────────────────────────────────────────────────────

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
PLATFORM_DIR="${MERIDIAN_ROOT}/intelligence/company/meridian_platform"
LOOM_BIN="${LOOM_BIN:-$MERIDIAN_ROOT/loom/target/release/loom}"
KERNEL_PATH="${MERIDIAN_ROOT}/kernel"
LOOM_CONFIG_BASE="${XDG_CONFIG_HOME:-${HOME}/.config}"
LOOM_CONFIG_ROOT="${LOOM_CONFIG_BASE}/meridian-loom"
LOOM_AGENT_CONFIG_DIR="${LOOM_CONFIG_ROOT}/agents"

NON_INTERACTIVE=0
CORE_MODE=0
TEAM_MODE=0

# Parse flags
prev_arg=""
for arg in "$@"; do
  case "$arg" in
    --non-interactive) NON_INTERACTIVE=1 ;;
    --mode=core)       CORE_MODE=1 ;;
    --mode=team)       TEAM_MODE=1 ;;
  esac
  if [ "$prev_arg" = "--mode" ]; then
    case "$arg" in
      core) CORE_MODE=1 ;;
      team) TEAM_MODE=1 ;;
    esac
  fi
  prev_arg="$arg"
done

# Env var override
if [ "${MERIDIAN_MODE:-}" = "core" ]; then CORE_MODE=1; fi
if [ "${MERIDIAN_MODE:-}" = "team" ]; then TEAM_MODE=1; fi

# Apply Core defaults (skips governance prompts, auto-selects execution)
if [ "$CORE_MODE" = "1" ]; then
  NON_INTERACTIVE=1
  export MERIDIAN_MODE="core"
  export MERIDIAN_INST_PLAN="${MERIDIAN_INST_PLAN:-core}"
  export MERIDIAN_ENABLE_GOVERNANCE="${MERIDIAN_ENABLE_GOVERNANCE:-yes}"
  export MERIDIAN_IMPORT_DEMO_PACK="${MERIDIAN_IMPORT_DEMO_PACK:-no}"
  export MERIDIAN_BRAIN_ROUTE_TYPE="${MERIDIAN_BRAIN_ROUTE_TYPE:-cli_session}"
  export MERIDIAN_BRAIN_PROVIDER_PROFILE="${MERIDIAN_BRAIN_PROVIDER_PROFILE:-claude_local}"
  export MERIDIAN_BRAIN_CLI_BIN="${MERIDIAN_BRAIN_CLI_BIN:-claude}"
  export MERIDIAN_BRAIN_AUTH_PROFILE="${MERIDIAN_BRAIN_AUTH_PROFILE:-claude_local}"
fi

# Apply Team defaults (same clean-slate start, governance depth exposed)
if [ "$TEAM_MODE" = "1" ]; then
  export MERIDIAN_MODE="team"
  export MERIDIAN_INST_PLAN="${MERIDIAN_INST_PLAN:-team}"
  export MERIDIAN_ENABLE_GOVERNANCE="${MERIDIAN_ENABLE_GOVERNANCE:-yes}"
  export MERIDIAN_IMPORT_DEMO_PACK="${MERIDIAN_IMPORT_DEMO_PACK:-no}"
fi

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
echo "  One product. One install. Choose your mode:"
echo ""
echo "    Core  — daily-use local agent runtime"
echo "            browser tasks, research, memory, scheduling, agent loops"
echo "            no governance expertise required to start"
echo ""
echo "    Team  — Core plus governance depth"
echo "            institution treasury, court rules, warrants, authority"
echo "            gates, and full audit surfaces"
echo ""

# Interactive mode selection — only if no mode was chosen via flag or env
if [ "$CORE_MODE" = "0" ] && [ "$TEAM_MODE" = "0" ] && [ "$NON_INTERACTIVE" = "0" ]; then
  while true; do
    read -rp "  Choose mode [core/team] (default: core): " _mode_choice
    _mode_choice="${_mode_choice:-core}"
    case "$_mode_choice" in
      core|Core|CORE)
        CORE_MODE=1
        export MERIDIAN_MODE="core"
        export MERIDIAN_INST_PLAN="${MERIDIAN_INST_PLAN:-core}"
        export MERIDIAN_ENABLE_GOVERNANCE="${MERIDIAN_ENABLE_GOVERNANCE:-yes}"
        export MERIDIAN_IMPORT_DEMO_PACK="${MERIDIAN_IMPORT_DEMO_PACK:-no}"
        export MERIDIAN_BRAIN_ROUTE_TYPE="${MERIDIAN_BRAIN_ROUTE_TYPE:-cli_session}"
        export MERIDIAN_BRAIN_PROVIDER_PROFILE="${MERIDIAN_BRAIN_PROVIDER_PROFILE:-claude_local}"
        export MERIDIAN_BRAIN_CLI_BIN="${MERIDIAN_BRAIN_CLI_BIN:-claude}"
        export MERIDIAN_BRAIN_AUTH_PROFILE="${MERIDIAN_BRAIN_AUTH_PROFILE:-claude_local}"
        break
        ;;
      team|Team|TEAM)
        TEAM_MODE=1
        export MERIDIAN_MODE="team"
        export MERIDIAN_INST_PLAN="${MERIDIAN_INST_PLAN:-team}"
        export MERIDIAN_ENABLE_GOVERNANCE="${MERIDIAN_ENABLE_GOVERNANCE:-yes}"
        export MERIDIAN_IMPORT_DEMO_PACK="${MERIDIAN_IMPORT_DEMO_PACK:-no}"
        break
        ;;
      *)
        echo "  Please enter 'core' or 'team'."
        ;;
    esac
  done
elif [ "$CORE_MODE" = "0" ] && [ "$TEAM_MODE" = "0" ] && [ "$NON_INTERACTIVE" = "1" ]; then
  # Non-interactive with no mode specified: default to Core
  CORE_MODE=1
  export MERIDIAN_MODE="core"
  export MERIDIAN_INST_PLAN="${MERIDIAN_INST_PLAN:-core}"
  export MERIDIAN_ENABLE_GOVERNANCE="${MERIDIAN_ENABLE_GOVERNANCE:-yes}"
  export MERIDIAN_IMPORT_DEMO_PACK="${MERIDIAN_IMPORT_DEMO_PACK:-no}"
  export MERIDIAN_BRAIN_ROUTE_TYPE="${MERIDIAN_BRAIN_ROUTE_TYPE:-cli_session}"
  export MERIDIAN_BRAIN_PROVIDER_PROFILE="${MERIDIAN_BRAIN_PROVIDER_PROFILE:-claude_local}"
  export MERIDIAN_BRAIN_CLI_BIN="${MERIDIAN_BRAIN_CLI_BIN:-claude}"
  export MERIDIAN_BRAIN_AUTH_PROFILE="${MERIDIAN_BRAIN_AUTH_PROFILE:-claude_local}"
fi

SELECTED_MODE="${MERIDIAN_MODE:-core}"
if [ "$TEAM_MODE" = "1" ]; then SELECTED_MODE="team"; fi
if [ "$CORE_MODE" = "1" ]; then SELECTED_MODE="core"; fi

echo ""
if [ "$SELECTED_MODE" = "core" ]; then
  echo "  Mode: Meridian Core"
  echo "  Quick setup with sensible defaults. No governance choices required."
  echo "  After setup: use ./scripts/core.sh for daily tasks."
else
  echo "  Mode: Meridian Team"
  echo "  Core plus governance depth. You will configure governance surfaces."
fi
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

# Plan is derived from mode; only prompt in Team mode for explicit override
if [ "$SELECTED_MODE" = "core" ]; then
  INST_PLAN="${MERIDIAN_INST_PLAN:-core}"
else
  INST_PLAN="$(prompt_or_default MERIDIAN_INST_PLAN "Governance tier (team / enterprise)" "team")"
fi

AGENT_NAME="$(prompt_or_default MERIDIAN_AGENT_NAME "First agent name" "Assistant")"
TEAM_PRESET="$(prompt_or_default MERIDIAN_TEAM_PRESET "Team preset (dev_team / generic_team)" "dev_team")"
AGENT_ROLE="$(prompt_or_default MERIDIAN_AGENT_ROLE "First agent role label (manager_tech_lead / architect / backend_engineer / frontend_engineer / platform_engineer / qa_reliability_engineer / security_reviewer)" "manager_tech_lead")"

IMPORT_DEMO="$(prompt_or_default MERIDIAN_IMPORT_DEMO_PACK "Import demo data pack? (yes / no)" "no")"
ENABLE_GOV="$(prompt_or_default MERIDIAN_ENABLE_GOVERNANCE "Enable governance gates? (yes / no)" "yes")"
BRAIN_ROUTE_TYPE="$(prompt_or_default MERIDIAN_BRAIN_ROUTE_TYPE "Execution route type (cli_session / http_json)" "cli_session")"
BRAIN_PROVIDER_PROFILE="$(prompt_or_default MERIDIAN_BRAIN_PROVIDER_PROFILE "Execution provider profile" "claude_local")"
BRAIN_MODEL="$(prompt_or_default MERIDIAN_BRAIN_MODEL "Execution model (blank for provider default)" "")"
BRAIN_AUTH_PROFILE="$(prompt_or_default MERIDIAN_BRAIN_AUTH_PROFILE "Execution auth profile name" "$BRAIN_PROVIDER_PROFILE")"
BRAIN_CLI_BIN_DEFAULT="claude"
if [ "$BRAIN_ROUTE_TYPE" = "http_json" ]; then
  BRAIN_CLI_BIN_DEFAULT=""
fi
BRAIN_CLI_BIN="$(prompt_or_default MERIDIAN_BRAIN_CLI_BIN "Execution CLI binary (blank if not using CLI route)" "$BRAIN_CLI_BIN_DEFAULT")"
BRAIN_CLI_HOME="$(prompt_or_default MERIDIAN_BRAIN_CLI_HOME "Execution CLI auth home (blank if default session)" "")"
BRAIN_ENDPOINT_DEFAULT=""
if [ "$BRAIN_ROUTE_TYPE" = "http_json" ]; then
  BRAIN_ENDPOINT_DEFAULT="https://example.local/v1/chat/completions"
fi
BRAIN_ENDPOINT="$(prompt_or_default MERIDIAN_BRAIN_ENDPOINT "Execution HTTP endpoint (blank if not using http_json)" "$BRAIN_ENDPOINT_DEFAULT")"
BRAIN_AUTH_ENV="$(prompt_or_default MERIDIAN_BRAIN_AUTH_ENV "Execution auth env var for HTTP route (blank if not using http_json)" "")"
BRAIN_KEY_ENV_POOL="$(prompt_or_default MERIDIAN_BRAIN_KEY_ENV_POOL "Execution auth env fallback pool (comma-separated, optional)" "")"

if [ "$BRAIN_ROUTE_TYPE" != "cli_session" ] && [ "$BRAIN_ROUTE_TYPE" != "http_json" ]; then
  echo "[onboard] Unsupported execution route type: $BRAIN_ROUTE_TYPE" >&2
  exit 1
fi
if [ "$BRAIN_ROUTE_TYPE" = "cli_session" ] && [ -z "$BRAIN_CLI_BIN" ]; then
  echo "[onboard] Execution CLI route requires MERIDIAN_BRAIN_CLI_BIN or an explicit CLI binary." >&2
  exit 1
fi
if [ "$BRAIN_ROUTE_TYPE" = "http_json" ] && [ -z "$BRAIN_ENDPOINT" ]; then
  echo "[onboard] Execution HTTP route requires MERIDIAN_BRAIN_ENDPOINT." >&2
  exit 1
fi
if [ "$BRAIN_ROUTE_TYPE" = "http_json" ] && [ -z "$BRAIN_AUTH_ENV" ] && [ -z "$BRAIN_KEY_ENV_POOL" ]; then
  echo "[onboard] Execution HTTP route requires MERIDIAN_BRAIN_AUTH_ENV or MERIDIAN_BRAIN_KEY_ENV_POOL." >&2
  exit 1
fi
if [ "$BRAIN_ROUTE_TYPE" = "cli_session" ] && ! command -v "$BRAIN_CLI_BIN" >/dev/null 2>&1; then
  echo "[onboard] Execution CLI binary not found on PATH: $BRAIN_CLI_BIN" >&2
  exit 1
fi
if [ "$BRAIN_ROUTE_TYPE" = "http_json" ]; then
  python3 - "$BRAIN_AUTH_ENV" "$BRAIN_KEY_ENV_POOL" <<'PY'
import os
import sys
primary = (sys.argv[1] or '').strip()
pool = [item.strip() for item in (sys.argv[2] or '').split(',') if item.strip()]
if primary and os.environ.get(primary, '').strip():
    raise SystemExit(0)
for name in pool:
    if os.environ.get(name, '').strip():
        raise SystemExit(0)
raise SystemExit(1)
PY
  if [ $? -ne 0 ]; then
    echo "[onboard] No HTTP execution auth secret is currently available in the configured environment variables." >&2
    exit 1
  fi
fi
if [ "$BRAIN_ROUTE_TYPE" = "cli_session" ]; then
  "$BRAIN_CLI_BIN" -p "Reply with exactly: MERIDIAN_BRAIN_POLICY_OK" --output-format text >/tmp/meridian_brain_policy_probe.txt 2>/tmp/meridian_brain_policy_probe.err || true
  if [ "$(tr -d '\r' </tmp/meridian_brain_policy_probe.txt 2>/dev/null | head -1)" != "MERIDIAN_BRAIN_POLICY_OK" ]; then
    echo "[onboard] Execution CLI route probe failed for $BRAIN_CLI_BIN." >&2
    cat /tmp/meridian_brain_policy_probe.err >&2 || true
    exit 1
  fi
fi
BRAIN_KEY_ENV_POOL_JSON="$(python3 - "$BRAIN_KEY_ENV_POOL" <<'PY'
import json
import sys
pool = [item.strip() for item in (sys.argv[1] or '').split(',') if item.strip()]
print(json.dumps(pool))
PY
)"
BRAIN_POLICY_SUMMARY="${BRAIN_ROUTE_TYPE}:${BRAIN_PROVIDER_PROFILE}:${BRAIN_MODEL:-provider_default}"

echo ""
echo "----------------------------------------------------------------"
echo "  Summary"
echo "----------------------------------------------------------------"
echo "  Institution:   $INST_NAME"
echo "  Owner ID:      $OWNER_ID"
echo "  Plan:          $INST_PLAN"
echo "  First agent:   $AGENT_NAME (role: $AGENT_ROLE)"
echo "  Team preset:   $TEAM_PRESET"
echo "  Demo pack:     $IMPORT_DEMO"
echo "  Governance:    $ENABLE_GOV"
echo "  Brain route:   $BRAIN_POLICY_SUMMARY"
echo "  Data root:     $MERIDIAN_ROOT/runtime"
echo "  Config root:   $LOOM_CONFIG_ROOT"
echo "  Agent configs: $LOOM_AGENT_CONFIG_DIR"
echo "  Team config:   ${HOME}/.meridian/team.json"
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

ONBOARD_RESULT="$(cd "$PLATFORM_DIR" && python3 - "$INST_NAME" "$OWNER_ID" "$INST_PLAN" "$BRAIN_ROUTE_TYPE" "$BRAIN_PROVIDER_PROFILE" "$BRAIN_MODEL" "$BRAIN_AUTH_PROFILE" "$BRAIN_CLI_BIN" "$BRAIN_CLI_HOME" "$BRAIN_ENDPOINT" "$BRAIN_AUTH_ENV" "$BRAIN_KEY_ENV_POOL_JSON" <<'PY'
import sys
import json
sys.path.insert(0, '.')
from onboarding import provision_institution

name = sys.argv[1]
owner_id = sys.argv[2]
plan = sys.argv[3]

brain_route_type = sys.argv[4]
brain_provider_profile = sys.argv[5]
brain_model = sys.argv[6]
brain_auth_profile = sys.argv[7]
brain_cli_bin = sys.argv[8]
brain_cli_home = sys.argv[9]
brain_endpoint = sys.argv[10]
brain_auth_env = sys.argv[11]
brain_key_env_pool = json.loads(sys.argv[12])

result = provision_institution(
    name,
    owner_id,
    plan,
    brain_route_type=brain_route_type,
    brain_provider_profile=brain_provider_profile,
    brain_model=brain_model,
    brain_auth_profile=brain_auth_profile,
    brain_cli_bin=brain_cli_bin,
    brain_cli_home=brain_cli_home,
    brain_endpoint=brain_endpoint,
    brain_auth_env=brain_auth_env,
    brain_key_env_pool=brain_key_env_pool,
)
print(json.dumps({
    'org_id': result['org_id'],
    'org_name': result['org'].get('name', ''),
    'org_slug': result['org'].get('slug', ''),
    'owner_id': owner_id,
    'plan': plan,
    'capsule_path': result['capsule_path'],
    'treasury_ledger': result['treasury']['ledger'],
    'institution_brain_policy': result.get('institution_brain_policy', {}),
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
import sys, json, os
result = json.load(sys.stdin)
state = {
    'org_id': result['org_id'],
    'org_slug': result.get('org_slug', ''),
    'owner_id': result['owner_id'],
    'plan': result['plan'],
    'mode': os.environ.get('MERIDIAN_MODE', 'core'),
    'execution_route': result.get('institution_brain_policy', {}),
    'onboarded_at': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    'source': 'onboard.sh',
}
with open('$ONBOARD_STATE_DIR/onboard_state.json', 'w') as f:
    json.dump(state, f, indent=2)
print(json.dumps(state, indent=2))
" > /dev/null

echo "[onboard] Onboarding state saved to: $ONBOARD_STATE_DIR/onboard_state.json"

# ── Seed intelligence gateway config ────────────────────────────────────
# dev-up.sh starts meridian_gateway.py, which refuses to start unless
# intelligence/meridian_config.json exists. bootstrap_full.sh handles this on
# the full install path; onboard.sh must do the same so `./scripts/onboard.sh`
# followed by `./scripts/dev-up.sh` works as documented in the README.

(
  cd "${MERIDIAN_INTELLIGENCE_ROOT:-${MERIDIAN_ROOT}/intelligence}"
  python3 - <<'PY' >/dev/null
from meridian_config import load_config, save_config
save_config(load_config(required=False))
PY
) || echo "[onboard] Warning: failed to seed intelligence/meridian_config.json; run 'python3 intelligence/meridian_setup.py' before dev-up." >&2

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
echo "  Mode: ${SELECTED_MODE}"
echo ""
echo "  What is local (your machine only):"
echo "    - Institution data:  $MERIDIAN_ROOT/intelligence/"
echo "    - Runtime state:     $MERIDIAN_ROOT/runtime/"
echo "    - Kernel governance: $MERIDIAN_ROOT/kernel/"
echo "    - Loom agents:       $MERIDIAN_ROOT/runtime/default/"
echo "    - Team semantics:    ${HOME}/.meridian/team.json"
echo ""

if [ "$SELECTED_MODE" = "core" ]; then
  echo "  ── Meridian Core next steps ──────────────────────────────"
  echo ""
  echo "  Daily tasks:"
  echo "    ./scripts/core.sh browse https://example.com"
  echo "    ./scripts/core.sh research \"echo hello\""
  echo "    ./scripts/core.sh remember my_note \"something to remember\""
  echo "    ./scripts/core.sh recall my_note"
  echo "    ./scripts/core.sh cap list"
  echo "    ./scripts/core.sh inspect"
  echo "    ./scripts/core.sh help"
  echo ""
  if [ "$AGENT_CREATED" = "1" ]; then
    echo "  Your agent:"
    echo "    \"$LOOM_BIN\" run-agent \"$AGENT_SLUG\""
    echo ""
  fi
  echo "  Public demo surfaces (not your local runtime):"
  echo "    https://app.welliam.codes is a public showcase."
  echo "    https://app.welliam.codes/proofs"
  echo "    https://app.welliam.codes/workflows"
else
  echo "  ── Meridian Team next steps ──────────────────────────────"
  echo ""
  echo "  Core daily tasks (same as Core mode):"
  echo "    ./scripts/core.sh browse https://example.com"
  echo "    ./scripts/core.sh research \"echo hello\""
  echo "    ./scripts/core.sh inspect"
  echo "    ./scripts/core.sh help"
  echo ""
  echo "  Governance depth surfaces:"
  echo "    MERIDIAN_ORG_ID=$ORG_ID MERIDIAN_WORKSPACE_ORG_ID=$ORG_ID ./scripts/dev-up.sh"
  echo "    http://127.0.0.1:8266/api/status           — runtime status"
  echo "    http://127.0.0.1:8266/api/treasury          — treasury state"
  echo "    http://127.0.0.1:8266/api/institution/template — institution template"
  echo ""
  echo "  Team semantics:"
  echo "    edit ~/.meridian/team.json to swap role / purpose / task_kind / scopes / aliases"
  echo "    or set MERIDIAN_TEAM_PRESET=generic_team to restore the legacy generic team model"
  echo ""
  echo "  Proof and audit surfaces:"
  _loom_display="${LOOM_BIN:-loom}"
  echo "    \"$_loom_display\" contract show"
  echo "    \"$_loom_display\" capsule inspect"
  echo "    \"$_loom_display\" parity report"
  if [ -z "${LOOM_BIN:-}" ]; then
    echo "    (build Loom first: cd \"$MERIDIAN_ROOT/loom\" && cargo build -p meridian-loom --release)"
  fi
  echo ""
  if [ "$AGENT_CREATED" = "1" ]; then
    echo "  Your agent:"
    echo "    \"$LOOM_BIN\" run-agent \"$AGENT_SLUG\""
    echo ""
  fi
fi

echo "    Your onboarding state: $ONBOARD_STATE_DIR/onboard_state.json"
echo "    (mode persisted: ${SELECTED_MODE})"
echo ""
