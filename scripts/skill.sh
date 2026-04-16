#!/usr/bin/env bash
# Meridian Skill — capability management for contributors
#
# The contributor-facing flow for creating, registering, inspecting,
# and running capabilities in Meridian Core.
#
# Flow:
#   1. scaffold  — create capability manifest + worker template + skill.yaml
#   2. implement — edit the worker file to add real logic
#   3. verify    — run the capability to confirm it works
#   4. promote   — register it for normal use
#   5. list      — discover available capabilities
#   6. inspect   — view full metadata
#   7. run       — execute from Core surface
#
# Usage:
#   ./scripts/skill.sh scaffold NAME [--kind python|wasm] [--action TYPE]
#   ./scripts/skill.sh list
#   ./scripts/skill.sh inspect NAME
#   ./scripts/skill.sh verify NAME [--agent AGENT] [--payload JSON]
#   ./scripts/skill.sh promote NAME
#   ./scripts/skill.sh run NAME [--agent AGENT] [--payload JSON]
#   ./scripts/skill.sh help
#
# Environment:
#   MERIDIAN_ROOT      override monorepo root
#   MERIDIAN_LOOM_ROOT override loom runtime root
#   MERIDIAN_ORG_ID    override org id
#   MERIDIAN_AGENT_ID  override agent id

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
LOOM_BIN="${MERIDIAN_ROOT}/loom/target/release/loom"
LOOM_ROOT="${MERIDIAN_LOOM_ROOT:-${MERIDIAN_ROOT}/runtime/default}"
KERNEL_PATH="${MERIDIAN_ROOT}/kernel"
ONBOARD_STATE="${MERIDIAN_ROOT}/runtime/onboard_state.json"

# ── Helpers ───────────────────────────────────────────────────────────────

die() { echo "[skill] ERROR: $*" >&2; exit 1; }

require_loom() {
    if [ ! -x "$LOOM_BIN" ]; then
        command -v loom >/dev/null 2>&1 && LOOM_BIN="$(command -v loom)" || \
          die "loom binary not found. Build: cd loom && cargo build --release"
    fi
}

require_runtime() {
    [ -d "$LOOM_ROOT" ] || die "Runtime root not found. Run: ./scripts/onboard.sh"
}

resolve_org_id() {
    if [ -n "${MERIDIAN_ORG_ID:-}" ]; then echo "$MERIDIAN_ORG_ID"; return; fi
    if [ -f "$ONBOARD_STATE" ]; then
        python3 -c "import json; d=json.load(open('$ONBOARD_STATE')); print(d.get('org_id',''))" 2>/dev/null || true
    fi
    if [ -f "${LOOM_ROOT}/loom.toml" ]; then
        grep -m1 '^org_id' "${LOOM_ROOT}/loom.toml" | sed 's/.*= *"\(.*\)"/\1/' 2>/dev/null || true
    fi
}

resolve_agent_id() {
    if [ -n "${MERIDIAN_AGENT_ID:-}" ]; then echo "$MERIDIAN_AGENT_ID"; return; fi
    local registry="${LOOM_ROOT}/agents/registry.json"
    [ -f "$registry" ] && python3 -c "
import json, sys
agents = json.load(open('$registry')).get('agents', [])
for a in agents:
    if a.get('agent_id') == 'aegis':
        print('aegis'); sys.exit(0)
print(agents[0]['agent_id'] if agents else '')
" 2>/dev/null || true
}

# ── Write companion skill.yaml ────────────────────────────────────────────

write_skill_yaml() {
    local dir="$1" name="$2" action="$3" kind="$4" worker="$5"
    cat >"${dir}/skill.yaml" <<EOF
# Meridian Skill Metadata
# Edit this file to describe your capability for contributors.
id: "${name}"
name: "${name}"
version: "0.1.0"
description: "Describe what this capability does."

runtime:
  kind: "${kind}"
  entrypoint: "${worker}"
  action_type: "${action}"

inputs:
  - name: message
    type: string
    description: "Primary input text or payload"
    required: false
  # Add more inputs as needed

outputs:
  - name: summary
    type: string
    description: "Primary result"
  - name: status
    type: string
    description: "completed | error"

permissions:
  # List what host permissions this capability uses
  # Options: network, filesystem, terminal, kv_memory, llm_inference
  - kv_memory

example_invocation:
  command: "./scripts/skill.sh run ${name} --payload '{\"message\": \"hello\"}'"
  expected_output: "status: completed, summary: ..."

notes: |
  Contribute: edit ${worker}, then run:
    ./scripts/skill.sh verify ${name}
    ./scripts/skill.sh promote ${name}
EOF
}

# ── Command: scaffold ─────────────────────────────────────────────────────

cmd_scaffold() {
    local name="${1:-}"
    [ -n "$name" ] || die "Usage: skill.sh scaffold NAME [--kind python|wasm] [--action TYPE] [--description TEXT]"
    shift

    local kind="python" action="execute" description="$name capability"
    while [ $# -gt 0 ]; do
        case "$1" in
            --kind)        kind="${2:-python}"; shift 2 ;;
            --action)      action="${2:-execute}"; shift 2 ;;
            --description) description="${2:-}"; shift 2 ;;
            *) shift ;;
        esac
    done

    require_loom; require_runtime

    echo "[skill] scaffolding: $name"

    local result
    result="$("$LOOM_BIN" capability scaffold \
        --name "$name" \
        --action-type "$action" \
        --resource "capability:${name}" \
        --description "$description" \
        --worker-kind "$kind" \
        --root "$LOOM_ROOT" 2>&1)"
    echo "$result"

    # Write per-capability skill.yaml alongside the manifest
    local cap_dir="${LOOM_ROOT}/capabilities/custom"
    local slug; slug="$(echo "$name" | tr '.' '-')"
    local worker_path="${LOOM_ROOT}/workers/python/${slug}.py"
    write_skill_yaml "$cap_dir" "$name" "$action" "$kind" "workers/python/${slug}.py"
    # Rename to per-capability file so multiple capabilities don't share one yaml
    mv "${cap_dir}/skill.yaml" "${cap_dir}/${slug}.skill.yaml" 2>/dev/null || true

    echo ""
    echo "[skill] next steps:"
    echo "  1. Edit the worker:  $worker_path"
    echo "  2. Edit metadata:    $cap_dir/${slug}.skill.yaml"
    echo "  3. Verify:           ./scripts/skill.sh verify $name"
    echo "  4. Promote:          ./scripts/skill.sh promote $name"
    echo "  5. Run:              ./scripts/skill.sh run $name"
}

# ── Command: list ─────────────────────────────────────────────────────────

cmd_list() {
    require_loom; require_runtime

    local cap_json
    cap_json="$("$LOOM_BIN" capability list --root "$LOOM_ROOT" --format json 2>/dev/null || true)"
    echo "$cap_json" | python3 -c "
import sys, json
data = json.loads(sys.stdin.read())
caps = data.get('capabilities', [])
print(f'[skill] {len(caps)} capabilities available:')
print()
builtin_caps = [c for c in caps if c.get('promotion_state') == 'builtin']
promoted_caps = [c for c in caps if c.get('promotion_state') == 'promoted']
candidate_caps = [c for c in caps if c.get('promotion_state') == 'candidate']
if promoted_caps:
    print('  --- Custom (promoted) ---')
    for c in promoted_caps:
        print(f'  {c[\"name\"]:40s}  [{c[\"action_type\"]}]  {c[\"description\"][:50]}')
if candidate_caps:
    print()
    print('  --- Custom (candidate — needs verify+promote) ---')
    for c in candidate_caps:
        print(f'  {c[\"name\"]:40s}  [{c[\"action_type\"]}]  {c[\"verification_status\"]}')
if builtin_caps:
    print()
    print('  --- Built-in ---')
    for c in builtin_caps:
        print(f'  {c[\"name\"]:40s}  [{c[\"action_type\"]}]')
print()
print('  Inspect: ./scripts/skill.sh inspect NAME')
print('  Run:     ./scripts/skill.sh run NAME')
"
}

# ── Command: inspect ──────────────────────────────────────────────────────

cmd_inspect() {
    local name="${1:-}"
    [ -n "$name" ] || die "Usage: skill.sh inspect NAME"
    require_loom; require_runtime

    local cap_json
    cap_json="$("$LOOM_BIN" capability show --name "$name" --root "$LOOM_ROOT" --format json 2>/dev/null || true)"

    # Locate skill.yaml for this capability (per-capability file takes priority)
    local slug; slug="$(echo "$name" | tr '.' '-')"
    local skill_yaml_per="${LOOM_ROOT}/capabilities/custom/${slug}.skill.yaml"
    local skill_yaml_shared="${LOOM_ROOT}/capabilities/custom/skill.yaml"
    local skill_yaml=""
    if [ -f "$skill_yaml_per" ]; then
        skill_yaml="$skill_yaml_per"
    elif [ -f "$skill_yaml_shared" ]; then
        # Only use shared skill.yaml if it describes this capability
        local yaml_id
        yaml_id="$(grep -m1 '^id:' "$skill_yaml_shared" 2>/dev/null | sed 's/id: *"\(.*\)"/\1/' | tr -d '"' | xargs)" || true
        [ "$yaml_id" = "$name" ] && skill_yaml="$skill_yaml_shared"
    fi

    # Pass skill_yaml path to Python via env to avoid quoting issues
    CAP_SKILL_YAML="${skill_yaml}" CAP_JSON_DATA="${cap_json}" python3 /dev/stdin <<'PYEOF'
import sys, json, re, datetime, os

cap_json_str = os.environ.get("CAP_JSON_DATA", "{}")
skill_yaml_path = os.environ.get("CAP_SKILL_YAML", "")

data = json.loads(cap_json_str)
skill_yaml_text = ""
if skill_yaml_path and os.path.isfile(skill_yaml_path):
    with open(skill_yaml_path, encoding="utf-8") as fh:
        skill_yaml_text = fh.read()


def _yaml_val(s):
    return s.strip().strip('"').strip("'")

def parse_yaml_simple(text):
    """Minimal YAML key extractor for skill.yaml — no external deps needed."""
    result = {}
    current_list_key = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # top-level key: (block follows — must check before key:value)
        m2 = re.match(r'^([a-z_]+):\s*$', line)
        if m2 and not line.startswith(" "):
            current_list_key = m2.group(1)
            if current_list_key not in result:
                result[current_list_key] = []
            continue
        # top-level key: value
        m = re.match(r'^([a-z_]+):\s*(.+)$', line)
        if m and not line.startswith(" "):
            k, v = m.group(1), _yaml_val(m.group(2))
            result[k] = v
            current_list_key = None
            continue
        # list item starting with sub-key: "  - name: value"
        m3k = re.match(r'^  - ([a-z_]+):\s*(.+)$', line)
        if m3k and current_list_key and isinstance(result.get(current_list_key), list):
            k2, v2 = m3k.group(1), _yaml_val(m3k.group(2))
            result[current_list_key].append({k2: v2})
            continue
        # plain list item: "  - value"
        m3 = re.match(r'^  - (.+)', line)
        if m3 and current_list_key and isinstance(result.get(current_list_key), list):
            result[current_list_key].append(m3.group(1).strip())
            continue
        # sub-key under list item (4-space indent)
        m4 = re.match(r'^    ([a-z_]+):\s*(.*)$', line)
        if m4 and current_list_key in ("inputs", "outputs"):
            lst = result.get(current_list_key, [])
            k2, v2 = m4.group(1), _yaml_val(m4.group(2))
            if lst and isinstance(lst[-1], dict):
                lst[-1][k2] = v2
    return result


sy = parse_yaml_simple(skill_yaml_text) if skill_yaml_text.strip() else {}

print("[skill] capability metadata — full inspector view")
print()
# Identity
print(f'  id:              {sy.get("id") or data.get("name")}')
print(f'  name:            {sy.get("name") or data.get("name")}')
print(f'  version:         {sy.get("version") or "(not set)"}')
print(f'  description:     {sy.get("description") or data.get("description")}')
print()
# Runtime
print(f'  action_type:     {data.get("action_type")}')
print(f'  worker_kind:     {data.get("worker_kind")}')
print(f'  worker_entry:    {data.get("worker_entry")}')
print(f'  runtime_lane:    {data.get("runtime_lane")}')
print()
# Inputs
inputs = [x for x in sy.get("inputs", []) if x]
if inputs:
    print("  inputs:")
    for inp in inputs:
        if isinstance(inp, dict):
            req = " (required)" if inp.get("required", "").lower() in ("true", "yes") else ""
            print(f'    - {inp.get("name","?")} [{inp.get("type","?")}]{req}: {inp.get("description","")}')
        else:
            print(f"    - {inp}")
else:
    print("  inputs:          (not documented in skill.yaml)")
print()
# Outputs
outputs = [x for x in sy.get("outputs", []) if x]
if outputs:
    print("  outputs:")
    for out in outputs:
        if isinstance(out, dict):
            print(f'    - {out.get("name","?")} [{out.get("type","?")}]: {out.get("description","")}')
        else:
            print(f"    - {out}")
else:
    print("  outputs:         (not documented in skill.yaml)")
print()
# Permissions
perms = [x for x in sy.get("permissions", []) if x]
if perms:
    print(f'  permissions:     {" | ".join(perms)}')
else:
    print("  permissions:     (not documented in skill.yaml)")
print()
# Example invocation
ex_cmd = ""
for line in skill_yaml_text.splitlines():
    m = re.match(r'\s+command:\s*"?(.+?)"?\s*$', line)
    if m:
        ex_cmd = m.group(1).strip().strip('"')
        break
if ex_cmd:
    print(f"  example:         {ex_cmd[:120]}")
print()
# Registration
print(f'  promotion_state: {data.get("promotion_state")}')
print(f'  verification:    {data.get("verification_status")}')
vt = data.get("last_verified_at", "")
if vt:
    try:
        dt = datetime.datetime.fromtimestamp(int(vt), tz=datetime.timezone.utc)
        print(f'  verified_at:     {dt.strftime("%Y-%m-%dT%H:%M:%SZ")}')
    except Exception:
        print(f"  verified_at:     {vt}")
ev = data.get("verification_evidence", {})
if ev.get("worker_result"):
    print(f'  last_result:     {ev["worker_result"]}')
PYEOF
}

# ── Command: verify ───────────────────────────────────────────────────────

cmd_verify() {
    local name="${1:-}"
    [ -n "$name" ] || die "Usage: skill.sh verify NAME [--agent AGENT] [--payload JSON]"
    shift

    local agent_override="" payload='{"message":"verify_check"}'
    while [ $# -gt 0 ]; do
        case "$1" in
            --agent)   agent_override="${2:-}"; shift 2 ;;
            --payload) payload="${2:-}"; shift 2 ;;
            *) shift ;;
        esac
    done

    require_loom; require_runtime

    local org_id; org_id="$(resolve_org_id)"
    local agent_id="${agent_override:-$(resolve_agent_id)}"
    [ -n "$org_id" ] || die "Could not resolve org_id."
    [ -n "$agent_id" ] || die "Could not resolve agent_id."

    echo "[skill] verifying: $name"
    local result
    result="$("$LOOM_BIN" capability verify \
        --name "$name" \
        --agent-id "$agent_id" \
        --kernel-path "$KERNEL_PATH" \
        --org-id "$org_id" \
        --payload-json "$payload" \
        --root "$LOOM_ROOT" \
        --format json 2>/dev/null)"
    echo "$result" | python3 -c "
import sys, json
data = json.loads(sys.stdin.read())
cap = data.get('capability', {})
print(f'[skill] verification result: {cap.get(\"verification_status\")}')
print(f'  note: {cap.get(\"verification_note\")}')
print(f'  job:  {cap.get(\"last_verification_job_id\")}')
if cap.get('verification_status') == 'verified':
    print()
    print('  Ready to promote: ./scripts/skill.sh promote $name')
"
}

# ── Command: promote ──────────────────────────────────────────────────────

cmd_promote() {
    local name="${1:-}"
    [ -n "$name" ] || die "Usage: skill.sh promote NAME"
    require_loom; require_runtime

    echo "[skill] promoting: $name"
    "$LOOM_BIN" capability promote --name "$name" --root "$LOOM_ROOT" 2>&1
    echo ""
    echo "[skill] capability promoted. Run it:"
    echo "  ./scripts/skill.sh run $name"
    echo "  ./scripts/core.sh cap run $name"
}

# ── Command: run ──────────────────────────────────────────────────────────

cmd_run() {
    local name="${1:-}"
    [ -n "$name" ] || die "Usage: skill.sh run NAME [--agent AGENT] [--payload JSON]"
    shift

    local agent_override="" payload='{}'
    while [ $# -gt 0 ]; do
        case "$1" in
            --agent)   agent_override="${2:-}"; shift 2 ;;
            --payload) payload="${2:-}"; shift 2 ;;
            *) shift ;;
        esac
    done

    require_loom; require_runtime

    local org_id; org_id="$(resolve_org_id)"
    local agent_id="${agent_override:-$(resolve_agent_id)}"
    [ -n "$org_id" ] || die "Could not resolve org_id."
    [ -n "$agent_id" ] || die "Could not resolve agent_id."

    # Look up action_type and resource from capability list
    local cap_json
    cap_json="$("$LOOM_BIN" capability list --root "$LOOM_ROOT" --format json 2>/dev/null || true)"
    local action_type resource
    action_type="$(echo "$cap_json" | python3 -c "
import sys,json
caps=json.loads(sys.stdin.read()).get('capabilities',[])
for c in caps:
    if c['name']=='$name':
        print(c['action_type']); break
" 2>/dev/null || echo "execute")"
    resource="capability:${name}"

    echo "[skill] running: $name"
    local out
    out="$("$LOOM_BIN" action execute \
        --agent-id "$agent_id" \
        --capability "$name" \
        --action-type "$action_type" \
        --resource "$resource" \
        --payload-json "$payload" \
        --kernel-path "$KERNEL_PATH" \
        --org-id "$org_id" \
        --root "$LOOM_ROOT" \
        --format json 2>/dev/null)"

    local result_path
    result_path="$(echo "$out" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('worker_result_path',''))" 2>/dev/null || true)"

    if [ -f "${result_path:-}" ]; then
        echo "[skill] result:"
        cat "$result_path" | python3 -m json.tool 2>/dev/null || cat "$result_path"
    else
        echo "$out" | python3 -c "
import sys,json
d=json.loads(sys.stdin.read())
print(f'  status:  {d.get(\"worker_status\")}')
print(f'  outcome: {d.get(\"runtime_outcome\")}')
" 2>/dev/null || echo "$out"
    fi
}

# ── Command: help ─────────────────────────────────────────────────────────

cmd_help() {
    cat <<'EOF'
Meridian Skill — capability management for contributors

Contributor flow:
  1. scaffold NAME      Create capability manifest + worker template + skill.yaml
  2. [edit worker]      Add your logic to the generated Python worker file
  3. verify NAME        Run the capability to confirm it works
  4. promote NAME       Register it for normal Core use
  5. list               Discover all capabilities
  6. inspect NAME       View full metadata
  7. run NAME           Execute from Core surface

Commands:
  scaffold NAME [--kind python|wasm] [--action TYPE] [--description TEXT]
  list
  inspect NAME
  verify NAME [--agent AGENT] [--payload JSON]
  promote NAME
  run NAME [--agent AGENT] [--payload JSON]
  help

Aliases (via core.sh):
  ./scripts/core.sh cap list
  ./scripts/core.sh cap inspect NAME
  ./scripts/core.sh cap run NAME [PAYLOAD]

Environment:
  MERIDIAN_ROOT      monorepo root
  MERIDIAN_LOOM_ROOT loom runtime root
  MERIDIAN_ORG_ID    org id override
  MERIDIAN_AGENT_ID  agent id override

Documentation:
  docs/CAPABILITY_GUIDE.md
EOF
}

# ── Main dispatch ─────────────────────────────────────────────────────────

COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    scaffold) cmd_scaffold "$@" ;;
    list)     cmd_list "$@" ;;
    inspect)  cmd_inspect "$@" ;;
    verify)   cmd_verify "$@" ;;
    promote)  cmd_promote "$@" ;;
    run)      cmd_run "$@" ;;
    help|--help) cmd_help ;;
    *)
        echo "[skill] Unknown command: $COMMAND" >&2
        cmd_help
        exit 1
        ;;
esac
