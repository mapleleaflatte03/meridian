#!/usr/bin/env bash
# Meridian Core — daily-use task runner
#
# Wraps loom CLI so you can complete common tasks without knowing
# the full loom flag surface.
#
# Usage:
#   ./scripts/core.sh browse URL               — navigate URL, show text
#   ./scripts/core.sh research "cmd [args]"    — run a bounded terminal command
#   ./scripts/core.sh remember KEY "VALUE"     — store a memory entry
#   ./scripts/core.sh recall KEY               — search memory by key prefix
#   ./scripts/core.sh schedule NAME every SEC  — add a recurring task
#   ./scripts/core.sh schedules                — list scheduled tasks
#   ./scripts/core.sh inspect                  — show last execution + agent state
#   ./scripts/core.sh status                   — show runtime status
#   ./scripts/core.sh help                     — show this help
#
# Environment overrides:
#   MERIDIAN_ROOT      override monorepo root
#   MERIDIAN_LOOM_ROOT override loom runtime root
#   MERIDIAN_ORG_ID    override org id
#   MERIDIAN_AGENT_ID  override agent id (default: first agent in registry)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MERIDIAN_ROOT="${MERIDIAN_ROOT:-$ROOT_DIR}"
LOOM_BIN="${MERIDIAN_ROOT}/loom/target/release/loom"
LOOM_ROOT="${MERIDIAN_LOOM_ROOT:-${MERIDIAN_ROOT}/runtime/default}"
KERNEL_PATH="${MERIDIAN_ROOT}/kernel"
ONBOARD_STATE="${MERIDIAN_ROOT}/runtime/onboard_state.json"

# ── Resolve org_id ────────────────────────────────────────────────────────

resolve_org_id() {
    if [ -n "${MERIDIAN_ORG_ID:-}" ]; then
        echo "$MERIDIAN_ORG_ID"
        return
    fi
    if [ -f "$ONBOARD_STATE" ]; then
        python3 -c "import json,sys; d=json.load(open('$ONBOARD_STATE')); print(d.get('org_id',''))" 2>/dev/null || true
    fi
    if [ -f "${LOOM_ROOT}/loom.toml" ]; then
        grep -m1 '^org_id' "${LOOM_ROOT}/loom.toml" | sed 's/.*= *"\(.*\)"/\1/' 2>/dev/null || true
    fi
}

# ── Resolve agent_id ──────────────────────────────────────────────────────

resolve_agent_id() {
    if [ -n "${MERIDIAN_AGENT_ID:-}" ]; then
        echo "$MERIDIAN_AGENT_ID"
        return
    fi
    local registry="${LOOM_ROOT}/agents/registry.json"
    if [ -f "$registry" ]; then
        python3 - "$registry" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
agents = data.get("agents", [])
# Prefer the aegis (QA gate / system agent) or first available
for a in agents:
    if a.get("agent_id") == "aegis":
        print("aegis")
        sys.exit(0)
if agents:
    print(agents[0]["agent_id"])
PY
    fi
}

# ── Guard checks ──────────────────────────────────────────────────────────

die() { echo "[core] ERROR: $*" >&2; exit 1; }

require_loom() {
    if [ ! -x "$LOOM_BIN" ]; then
        if command -v loom >/dev/null 2>&1; then
            LOOM_BIN="$(command -v loom)"
        else
            die "loom binary not found at $LOOM_BIN. Run: cd loom && cargo build --release"
        fi
    fi
}

require_runtime() {
    if [ ! -d "$LOOM_ROOT" ]; then
        die "Loom runtime root not found at $LOOM_ROOT. Complete onboarding first: ./scripts/onboard.sh"
    fi
}

# ── Show result ───────────────────────────────────────────────────────────

show_result() {
    local result_path="$1"
    python3 - "$result_path" <<'PY'
import json, sys

try:
    data = json.load(open(sys.argv[1]))
except Exception:
    print("(could not parse result)")
    sys.exit(0)

action = data.get("action_type", "")
host_resp = data.get("host_response_json") or {}

# Terminal exec
if "stdout_utf8" in host_resp:
    out = (host_resp.get("stdout_utf8") or "").strip()
    err = (host_resp.get("stderr_utf8") or "").strip()
    if out:
        print(out)
    if err:
        print("stderr:", err, file=sys.stderr)
    sys.exit(0)

# Browser navigate
nav = host_resp.get("navigate") or {}
text = nav.get("body_text") or nav.get("extracted_text") or host_resp.get("body_text") or ""
url = nav.get("url") or ""
title = nav.get("title") or ""
if url or title or text:
    if title:
        print(f"Title: {title}")
    if url:
        print(f"URL:   {url}")
    if text:
        print()
        print(text[:2000])
    sys.exit(0)

# Generic
for k in ("output", "result", "summary", "text", "value"):
    if k in data:
        print(data[k])
        sys.exit(0)

print(json.dumps(data, indent=2)[:1000])
PY
}

# ── Command: browse ───────────────────────────────────────────────────────

cmd_browse() {
    local url="${1:-}"
    [ -n "$url" ] || die "Usage: core.sh browse URL"
    require_loom; require_runtime

    local org_id; org_id="$(resolve_org_id)"
    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$org_id" ] || die "Could not resolve org_id. Run onboard.sh first."
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    echo "[core] browse: $url"
    local out
    out="$("$LOOM_BIN" action execute \
        --agent-id "$agent_id" \
        --capability "loom.browser.navigate.v1" \
        --action-type "browse" \
        --resource "$url" \
        --payload-json "{\"url\":\"$url\",\"extract_text\":true}" \
        --kernel-path "$KERNEL_PATH" \
        --org-id "$org_id" \
        --root "$LOOM_ROOT" \
        --format json 2>/dev/null)"
    local result_path
    result_path="$(echo "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('worker_result_path',''))" 2>/dev/null || true)"
    if [ -f "${result_path:-}" ]; then
        show_result "$result_path"
    else
        echo "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('worker_status',''),d.get('runtime_outcome',''))" 2>/dev/null || echo "$out"
    fi
}

# ── Command: research ─────────────────────────────────────────────────────

cmd_research() {
    local query="${1:-}"
    [ -n "$query" ] || die "Usage: core.sh research \"command [args]\""
    require_loom; require_runtime

    local org_id; org_id="$(resolve_org_id)"
    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$org_id" ] || die "Could not resolve org_id. Run onboard.sh first."
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    # Build argv from the query string (split on spaces)
    local argv_json
    argv_json="$(python3 -c "import sys,json; q=sys.argv[1]; parts=q.split(); print(json.dumps(parts))" "$query")"

    echo "[core] research: $query"
    local out
    out="$("$LOOM_BIN" action execute \
        --agent-id "$agent_id" \
        --capability "loom.terminal.exec.v1" \
        --action-type "execute" \
        --resource "capability:loom.terminal.exec.v1" \
        --payload-json "{\"argv\":$argv_json}" \
        --kernel-path "$KERNEL_PATH" \
        --org-id "$org_id" \
        --root "$LOOM_ROOT" \
        --format json 2>/dev/null)"
    local result_path
    result_path="$(echo "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('worker_result_path',''))" 2>/dev/null || true)"
    if [ -f "${result_path:-}" ]; then
        show_result "$result_path"
    else
        echo "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('worker_status',''))" 2>/dev/null || echo "$out"
    fi
}

# ── Command: remember ─────────────────────────────────────────────────────

cmd_remember() {
    local key="${1:-}"; local value="${2:-}"
    [ -n "$key" ] && [ -n "$value" ] || die "Usage: core.sh remember KEY \"VALUE\""
    require_loom; require_runtime

    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    "$LOOM_BIN" memory write \
        --agent-id "$agent_id" \
        --category "core" \
        --key "$key" \
        --content "$value" \
        --source "core_task_runner" \
        --root "$LOOM_ROOT" \
        --format json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'[core] stored: {d.get(\"key\")} -> {d.get(\"content\",\"\")[:60]}')" 2>/dev/null || echo "[core] stored: $key"
}

# ── Command: recall ───────────────────────────────────────────────────────

cmd_recall() {
    local prefix="${1:-}"
    require_loom; require_runtime

    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    local args=("--agent-id" "$agent_id" "--category" "core" "--root" "$LOOM_ROOT" "--format" "json")
    if [ -n "$prefix" ]; then args+=("--key-prefix" "$prefix"); fi

    local mem_json
    mem_json="$("$LOOM_BIN" memory search "${args[@]}" 2>/dev/null || true)"
    echo "$mem_json" | python3 -c "
import sys, json
try:
    entries = json.loads(sys.stdin.read())
except Exception:
    entries = []
if not entries:
    print('[core] no memory entries found')
    raise SystemExit(0)
for e in entries:
    print(f'  {e.get(\"key\")}: {e.get(\"content\",\"\")[:80]}')
"
}

# ── Command: schedule ─────────────────────────────────────────────────────

cmd_schedule() {
    local name="${1:-}"; local every="${2:-3600}"
    [ -n "$name" ] || die "Usage: core.sh schedule NAME [every_seconds]"
    require_loom; require_runtime

    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    local result
    result="$("$LOOM_BIN" heartbeat schedule \
        --agent-id "$agent_id" \
        --capability "loom.system.info.v1" \
        --heartbeat-id "core-$(echo "$name" | tr ' ' '-' | tr '[:upper:]' '[:lower:]')-$(date +%s)" \
        --schedule "interval" \
        --every-seconds "$every" \
        --root "$LOOM_ROOT" \
        --format json 2>/dev/null)"
    local hb_id
    hb_id="$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('heartbeat_id',''))" 2>/dev/null || true)"
    echo "[core] scheduled: $name every ${every}s (id: $hb_id)"
}

# ── Command: schedules ────────────────────────────────────────────────────

cmd_schedules() {
    require_loom; require_runtime

    local hb_json
    hb_json="$("$LOOM_BIN" heartbeat list --root "$LOOM_ROOT" --format json 2>/dev/null || true)"
    echo "$hb_json" | python3 -c "
import sys, json
try:
    entries = json.loads(sys.stdin.read())
except Exception:
    entries = []
if not entries:
    print('[core] no scheduled tasks found')
    raise SystemExit(0)
print(f'[core] {len(entries)} scheduled task(s):')
for e in entries:
    every = e.get('every_seconds') or '?'
    cap = e.get('capability_name', '?')
    hid = e.get('heartbeat_id', '?')
    status = 'paused' if e.get('paused') else 'active'
    print(f'  {hid}  every {every}s  [{cap}]  {status}')
"
}

# ── Command: inspect ──────────────────────────────────────────────────────

cmd_inspect() {
    require_loom; require_runtime

    echo "[core] parity report:"
    "$LOOM_BIN" parity report --root "$LOOM_ROOT" 2>/dev/null | head -30 || echo "  (no parity report yet)"
    echo ""
    echo "[core] recent runtime events:"
    local stream="${LOOM_ROOT}/artifacts/runtime/events/stream.jsonl"
    if [ -f "$stream" ]; then
        tail -5 "$stream" | python3 - <<'PY'
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        d = json.loads(line)
        print(f"  {d.get('event_id','?')[:80]}")
        print(f"    action={d.get('action_type','?')}  outcome={d.get('runtime_outcome','?')}  decision={d.get('overall_decision','?')}")
    except Exception:
        print(f"  {line[:100]}")
PY
    else
        echo "  (no events yet)"
    fi
    echo ""
    echo "[core] heartbeat status:"
    "$LOOM_BIN" heartbeat status --root "$LOOM_ROOT" --format json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  enabled={d.get(\"enabled_count\",0)} total={d.get(\"total_count\",0)} due={d.get(\"due_count\",0)}')" 2>/dev/null || echo "  (not available)"
}

# ── Command: status ───────────────────────────────────────────────────────

cmd_status() {
    require_loom; require_runtime
    "$LOOM_BIN" status --root "$LOOM_ROOT" 2>/dev/null
}

# ── Command: cap ──────────────────────────────────────────────────────────
# Delegates to skill.sh for capability discovery and execution

cmd_cap() {
    local subcmd="${1:-list}"
    shift || true
    local skill_script="${ROOT_DIR}/scripts/skill.sh"
    [ -x "$skill_script" ] || die "skill.sh not found at $skill_script"
    MERIDIAN_ROOT="$ROOT_DIR" MERIDIAN_LOOM_ROOT="$LOOM_ROOT" \
      bash "$skill_script" "$subcmd" "$@"
}

# ── Command: help ─────────────────────────────────────────────────────────

cmd_help() {
    cat <<'EOF'
Meridian Core — daily-use task runner

Commands:
  browse URL               Navigate to URL, extract and show text
  research "cmd [args]"   Run a bounded terminal command
  remember KEY "VALUE"    Store a memory entry (persistent across sessions)
  recall [KEY_PREFIX]     Search stored memory
  schedule NAME [SEC]     Add a recurring task (default: every 3600s)
  schedules               List all scheduled tasks
  inspect                 Show last execution receipts and agent state
  status                  Show full runtime status
  cap list                List available capabilities
  cap inspect NAME        Show capability metadata
  cap run NAME [PAYLOAD]  Run a capability by name
  help                    Show this help

Capability contributor flow:
  ./scripts/skill.sh scaffold my.cap.v1
  ./scripts/skill.sh verify my.cap.v1
  ./scripts/skill.sh promote my.cap.v1
  ./scripts/core.sh cap run my.cap.v1

Environment:
  MERIDIAN_ROOT      monorepo root (default: auto-detected)
  MERIDIAN_LOOM_ROOT loom runtime root (default: runtime/default)
  MERIDIAN_ORG_ID    org id override
  MERIDIAN_AGENT_ID  agent id override

First time:
  ./scripts/onboard.sh          interactive setup
  ./scripts/onboard.sh --mode core  quick Core setup with defaults
EOF
}

# ── Main dispatch ─────────────────────────────────────────────────────────

COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    browse)      cmd_browse "$@" ;;
    research)    cmd_research "$@" ;;
    remember)    cmd_remember "$@" ;;
    recall)      cmd_recall "$@" ;;
    schedule)    cmd_schedule "$@" ;;
    schedules)   cmd_schedules "$@" ;;
    inspect)     cmd_inspect "$@" ;;
    status)      cmd_status "$@" ;;
    cap)         cmd_cap "$@" ;;
    help|--help) cmd_help ;;
    *)
        echo "[core] Unknown command: $COMMAND" >&2
        cmd_help
        exit 1
        ;;
esac
