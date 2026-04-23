#!/usr/bin/env bash
# Meridian Core — daily-use task runner
#
# Wraps loom CLI so you can complete common tasks without knowing
# the full loom flag surface.
#
# Usage:
#   ./scripts/core.sh browse URL               — navigate URL, show text
#   ./scripts/core.sh ask [--file PATH ...] "TASK" — run a prompt with optional file attachments
#   ./scripts/core.sh research "cmd [args]"    — run a bounded terminal command
#   ./scripts/core.sh remember KEY "VALUE"     — store a memory entry
#   ./scripts/core.sh recall KEY               — search memory by key prefix
#   ./scripts/core.sh memory receipts          — show recent memory receipts
#   ./scripts/core.sh memory graph SOURCE_REF  — inspect memory graph fork/root
#   ./scripts/core.sh schedule NAME every SEC  — add a recurring task
#   ./scripts/core.sh schedules                — list scheduled tasks
#   ./scripts/core.sh agent inspect            — show live agent/operator state
#   ./scripts/core.sh job list                 — inspect recent runtime jobs
#   ./scripts/core.sh channel health           — inspect channel health/deliveries
#   ./scripts/core.sh queue status             — inspect local queue depth
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
MERIDIAN_GATEWAY_URL="${MERIDIAN_GATEWAY_URL:-http://127.0.0.1:8266}"
CORE_STATE_DIR="${LOOM_ROOT}/state/core_cli"
CORE_CURRENT_SESSION_FILE="${CORE_STATE_DIR}/current_session.json"
CORE_SESSION_REGISTRY_FILE="${CORE_STATE_DIR}/sessions.json"
CORE_LAST_RESPONSE_FILE="${CORE_STATE_DIR}/last_response.json"
CORE_LAST_OUTPUT_FILE="${CORE_STATE_DIR}/last_output.txt"
CORE_LAST_EXPORT_DIR_FILE="${CORE_STATE_DIR}/last_export_dir.txt"
CORE_ARTIFACT_LONG_THRESHOLD="${MERIDIAN_CORE_LONG_OUTPUT_CHARS:-4000}"
CORE_ARTIFACT_LONG_LINES="${MERIDIAN_CORE_LONG_OUTPUT_LINES:-80}"

# ── Resolve org_id ────────────────────────────────────────────────────────
#
# Truth order: explicit env → kernel-bound org via `loom agent resolve` →
# loom.toml → onboard_state.json. The kernel-bound value is authoritative
# because action execute needs the org the kernel actually registered.

resolve_org_id() {
    if [ -n "${MERIDIAN_ORG_ID:-}" ]; then
        echo "$MERIDIAN_ORG_ID"
        return
    fi
    local kernel_org
    kernel_org="$(_resolve_via_loom bound_org_id 2>/dev/null || true)"
    if [ -n "$kernel_org" ]; then
        echo "$kernel_org"
        return
    fi
    if [ -f "${LOOM_ROOT}/loom.toml" ]; then
        local toml_org
        toml_org="$(grep -m1 '^org_id' "${LOOM_ROOT}/loom.toml" | sed 's/.*= *"\(.*\)"/\1/' 2>/dev/null || true)"
        if [ -n "$toml_org" ]; then
            echo "$toml_org"
            return
        fi
    fi
    if [ -f "$ONBOARD_STATE" ]; then
        python3 -c "import json,sys; d=json.load(open('$ONBOARD_STATE')); print(d.get('org_id',''))" 2>/dev/null || true
    fi
}

# ── Resolve agent_id ──────────────────────────────────────────────────────
#
# Registry exposes economy keys (aegis, atlas, ...). The runtime needs the
# kernel-registered agent_id (agent_aegis). Use `loom agent resolve` to map
# from economy key to the actual id the runtime accepts.

resolve_agent_id() {
    if [ -n "${MERIDIAN_AGENT_ID:-}" ]; then
        echo "$MERIDIAN_AGENT_ID"
        return
    fi
    local key=""
    local registry="${LOOM_ROOT}/agents/registry.json"
    if [ -f "$registry" ]; then
        key="$(python3 - "$registry" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
agents = data.get("agents", [])
for a in agents:
    if a.get("agent_id") == "aegis":
        print("aegis"); sys.exit(0)
if agents:
    print(agents[0]["agent_id"])
PY
        )"
    fi
    if [ -z "$key" ]; then
        return
    fi
    local resolved
    resolved="$(_resolve_via_loom agent_id "$key" 2>/dev/null || true)"
    if [ -n "$resolved" ]; then
        echo "$resolved"
    else
        echo "$key"
    fi
}

# Resolve the personal-agent loop name/slug for run-agent/channel surfaces.
# Truth order: explicit env → active run/personal-agents state dir → first
# registry entry under agents/personal/*.
resolve_personal_agent_name() {
    if [ -n "${MERIDIAN_PERSONAL_AGENT_NAME:-}" ]; then
        echo "$MERIDIAN_PERSONAL_AGENT_NAME"
        return
    fi
    local run_dir="${LOOM_ROOT}/run/personal-agents"
    if [ -d "$run_dir" ]; then
        local active
        active="$(find "$run_dir" -maxdepth 1 -type f -name '*.state.json' -printf '%f\n' 2>/dev/null | sed 's/\.state\.json$//' | head -n1)"
        if [ -n "$active" ]; then
            echo "$active"
            return
        fi
    fi
    local registry="${LOOM_ROOT}/agents/registry.json"
    if [ -f "$registry" ]; then
        python3 - "$registry" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
for agent in data.get("agents", []):
    session_root = str(agent.get("session_root") or "")
    if "agents/personal/" in session_root:
        parts = [p for p in session_root.split("/") if p]
        if "personal" in parts:
            idx = parts.index("personal")
            if idx + 1 < len(parts):
                print(parts[idx + 1])
                raise SystemExit(0)
PY
    fi
}

# Shared helper: run `loom agent resolve` and extract a field.
# Usage: _resolve_via_loom FIELD [AGENT_KEY]
_resolve_via_loom() {
    local field="$1"
    local agent_key="${2:-aegis}"
    [ -x "$LOOM_BIN" ] || return 1
    "$LOOM_BIN" agent resolve --agent-id "$agent_key" --root "$LOOM_ROOT" --format json 2>/dev/null \
        | python3 -c "import sys,json;
try:
    d=json.load(sys.stdin)
    print(d.get('$field',''))
except Exception:
    pass" 2>/dev/null
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

ensure_core_state_dir() {
    mkdir -p "$CORE_STATE_DIR"
}

# ── File attachment helpers ────────────────────────────────────────────────

build_attachments_json() {
    # Reads file paths from arguments, returns a JSON array of attachment objects.
    # Usage: build_attachments_json /path/a.py /path/b.txt
    # Returns: [{"name":"a.py","content":"...","mime_type":"text/x-python"},...]
    # Binary files are rejected with a warning on stderr.
    python3 - "$@" <<'PY'
import json, mimetypes, os, sys

MAX_FILE_BYTES = 512 * 1024  # 512 KiB per file
MAX_TOTAL_BYTES = 2 * 1024 * 1024  # 2 MiB total
attachments = []
total = 0
for path in sys.argv[1:]:
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        print(f"[core] warning: file not found: {path}", file=sys.stderr)
        continue
    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        print(f"[core] warning: skipping {path} ({size} bytes > {MAX_FILE_BYTES} limit)", file=sys.stderr)
        continue
    if total + size > MAX_TOTAL_BYTES:
        print(f"[core] warning: total attachment size exceeded, skipping {path}", file=sys.stderr)
        continue
    # Detect binary files
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
        if b"\x00" in chunk:
            print(f"[core] warning: skipping binary file: {path}", file=sys.stderr)
            continue
        content = open(path, "r", encoding="utf-8", errors="replace").read()
    except Exception as exc:
        print(f"[core] warning: could not read {path}: {exc}", file=sys.stderr)
        continue
    mime = mimetypes.guess_type(path)[0] or "text/plain"
    attachments.append({
        "name": os.path.basename(path),
        "content": content,
        "mime_type": mime,
    })
    total += size
print(json.dumps(attachments, ensure_ascii=False))
PY
}

# ── Artifact-safe output rendering ────────────────────────────────────────
# Detects long outputs and auto-saves to a file, showing a truncated preview
# in the terminal with a pointer to the full output.

render_output_safe() {
    local output_text="$1"
    local output_chars output_lines
    output_chars="${#output_text}"
    output_lines="$(printf '%s' "$output_text" | wc -l)"

    if [ "$output_chars" -gt "$CORE_ARTIFACT_LONG_THRESHOLD" ] || [ "$output_lines" -gt "$CORE_ARTIFACT_LONG_LINES" ]; then
        # Save full output to state and show truncated preview
        local preview_lines=40
        local preview
        preview="$(printf '%s' "$output_text" | head -n "$preview_lines")"
        local preview_chars="${#preview}"
        local remaining_chars=$((output_chars - preview_chars))
        local remaining_lines=$((output_lines - preview_lines))
        if [ "$remaining_lines" -lt 0 ]; then remaining_lines=0; fi

        printf '%s\n' "$preview"
        echo ""
        echo "[core] output truncated (${output_chars} chars, ${output_lines} lines)"
        echo "[core] full output: $CORE_LAST_OUTPUT_FILE"
        echo "[core] view:  ./scripts/core.sh response page"
    else
        printf '%s\n' "$output_text"
    fi
}

normalize_core_session_id() {
    python3 - "$1" <<'PY'
import re, sys
raw = str(sys.argv[1] or "").strip().lower()
raw = re.sub(r"[^a-z0-9._-]+", "-", raw)
raw = re.sub(r"-{2,}", "-", raw).strip("-.")
print(raw[:80])
PY
}

generate_core_session_id() {
    date -u +"core-%Y%m%d-%H%M%S"
}

read_current_core_session_id() {
    if [ -n "${MERIDIAN_SESSION_ID:-}" ]; then
        normalize_core_session_id "$MERIDIAN_SESSION_ID"
        return
    fi
    if [ -f "$CORE_CURRENT_SESSION_FILE" ]; then
        python3 - "$CORE_CURRENT_SESSION_FILE" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    data = {}
print(str(data.get("session_id") or "").strip())
PY
        return
    fi
    echo "core-main"
}

write_current_core_session_id() {
    local session_id="$1"
    ensure_core_state_dir
    python3 - "$CORE_CURRENT_SESSION_FILE" "$session_id" <<'PY'
import json, sys, time
path, session_id = sys.argv[1], sys.argv[2]
payload = {"session_id": session_id, "updated_at_unix_ms": int(time.time() * 1000)}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY
}

register_core_session() {
    local session_id="$1"
    ensure_core_state_dir
    python3 - "$CORE_SESSION_REGISTRY_FILE" "$session_id" <<'PY'
import json, os, sys, time
path, session_id = sys.argv[1], sys.argv[2]
data = {"sessions": {}}
if os.path.exists(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        data = {"sessions": {}}
sessions = data.setdefault("sessions", {})
entry = sessions.get(session_id, {})
now = int(time.time() * 1000)
entry["session_id"] = session_id
entry["last_used_unix_ms"] = now
entry["created_unix_ms"] = int(entry.get("created_unix_ms") or now)
sessions[session_id] = entry
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

resolve_core_session_id() {
    local raw_session
    raw_session="$(read_current_core_session_id)"
    local session_id
    session_id="$(normalize_core_session_id "$raw_session")"
    if [ -z "$session_id" ]; then
        session_id="core-main"
    fi
    write_current_core_session_id "$session_id"
    register_core_session "$session_id"
    echo "$session_id"
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
final_url = nav.get("url") or host_resp.get("final_url") or ""
title = nav.get("title") or ""
text = (
    nav.get("body_text")
    or nav.get("extracted_text")
    or host_resp.get("body_text")
    or host_resp.get("body_excerpt_utf8")
    or ""
)
http_status = host_resp.get("http_status")
if final_url or title or text or http_status is not None:
    if title:
        print(f"Title:  {title}")
    if final_url:
        print(f"URL:    {final_url}")
    if http_status is not None:
        print(f"Status: {http_status}")
    if text:
        print()
        import re as _re
        # Strip HTML tags for a readable excerpt.
        excerpt = _re.sub(r"<[^>]+>", " ", text)
        excerpt = _re.sub(r"\s+", " ", excerpt).strip()
        print(excerpt[:2000])
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

cmd_ask() {
    local goal=""
    local -a file_paths=()
    # Parse arguments: support --file PATH (repeatable) before or after the goal
    while [ $# -gt 0 ]; do
        case "$1" in
            --file|-f)
                [ -n "${2:-}" ] || die "Usage: --file requires a PATH argument"
                file_paths+=("$2")
                shift 2
                ;;
            *)
                if [ -z "$goal" ]; then
                    goal="$1"
                else
                    goal="$goal $1"
                fi
                shift
                ;;
        esac
    done
    [ -n "$goal" ] || die "Usage: core.sh ask [--file PATH ...] \"TASK\""
    require_runtime
    ensure_core_state_dir

    # Build attachment JSON if files were specified
    local attachments_json="[]"
    if [ ${#file_paths[@]} -gt 0 ]; then
        attachments_json="$(build_attachments_json "${file_paths[@]}")"
        local att_count
        att_count="$(echo "$attachments_json" | python3 -c "import sys,json; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo "0")"
        if [ "$att_count" != "0" ]; then
            echo "[core] attached $att_count file(s)" >&2
        fi
    fi

    local session_id
    session_id="$(resolve_core_session_id)"
    local raw_output
    raw_output="$(python3 - "$MERIDIAN_GATEWAY_URL" "$goal" "$session_id" "$CORE_LAST_RESPONSE_FILE" "$CORE_LAST_OUTPUT_FILE" "$attachments_json" <<'PY'
import json, sys, urllib.request, urllib.error

base_url, goal, session_id, last_response_path, last_output_path, attachments_json = sys.argv[1:7]
attachments = json.loads(attachments_json)
payload = {"goal": goal, "session_id": session_id}
if attachments:
    payload["attachments"] = attachments
request = urllib.request.Request(
    f"{base_url.rstrip('/')}/api/run",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=180) as response:
        raw = response.read().decode("utf-8", "replace")
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", "replace")
    print(f"[core] gateway http error {exc.code}: {detail}", file=sys.stderr)
    raise SystemExit(1)
except Exception as exc:
    print(f"[core] gateway request failed: {exc}", file=sys.stderr)
    raise SystemExit(1)

try:
    data = json.loads(raw)
except Exception:
    print(raw)
    raise SystemExit(0)

output = str(data.get("output") or "").strip()
response_record = {
    "recorded_for": "core.sh ask",
    "session_id": session_id,
    "session_key": data.get("session_key") or f"web_api:{session_id}",
    "attachment_count": len(attachments),
    "recorded_payload": data,
}
with open(last_response_path, "w", encoding="utf-8") as fh:
    json.dump(response_record, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
with open(last_output_path, "w", encoding="utf-8") as fh:
    fh.write(output)
    if output and not output.endswith("\n"):
        fh.write("\n")
if output:
    print(output)
trace = dict(data.get("constitutional_trace") or {})
route = dict(trace.get("route") or {})
mode = str(route.get("mode") or "").strip()
workers = route.get("workers") or []
if mode or workers:
    workers_text = ", ".join(str(item) for item in workers) if workers else "-"
    print(f"\n[core] route={mode or '?'} workers={workers_text} session={data.get('session_key') or session_id}", file=sys.stderr)
PY
    )"

    # Artifact-safe rendering: truncate long output with pointer to full file
    if [ -n "$raw_output" ]; then
        render_output_safe "$raw_output"
    fi
}

cmd_response() {
    local subcmd="${1:-show}"
    shift || true
    require_runtime
    ensure_core_state_dir

    case "$subcmd" in
        show)
            [ -f "$CORE_LAST_OUTPUT_FILE" ] || die "No Core response captured yet. Run: ./scripts/core.sh ask \"TASK\""
            cat "$CORE_LAST_OUTPUT_FILE"
            ;;
        path)
            [ -f "$CORE_LAST_RESPONSE_FILE" ] || die "No Core response captured yet. Run: ./scripts/core.sh ask \"TASK\""
            echo "$CORE_LAST_RESPONSE_FILE"
            ;;
        json)
            [ -f "$CORE_LAST_RESPONSE_FILE" ] || die "No Core response captured yet. Run: ./scripts/core.sh ask \"TASK\""
            cat "$CORE_LAST_RESPONSE_FILE"
            ;;
        meta)
            [ -f "$CORE_LAST_RESPONSE_FILE" ] || die "No Core response captured yet. Run: ./scripts/core.sh ask \"TASK\""
            python3 - "$CORE_LAST_RESPONSE_FILE" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
payload = dict(data.get("recorded_payload") or {})
trace = dict(payload.get("constitutional_trace") or {})
route = dict(trace.get("route") or {})
workers = route.get("workers") or []
print(f"session_key: {payload.get('session_key') or data.get('session_key') or ''}")
print(f"route_mode: {route.get('mode') or ''}")
print(f"route_reason: {route.get('reason') or ''}")
print(f"workers: {', '.join(str(item) for item in workers) if workers else '-'}")
print(f"output_chars: {len(str(payload.get('output') or ''))}")
PY
            ;;
        export)
            local out_dir="${1:-}"
            [ -n "$out_dir" ] || die "Usage: core.sh response export OUT_DIR"
            [ -f "$CORE_LAST_RESPONSE_FILE" ] || die "No Core response captured yet. Run: ./scripts/core.sh ask \"TASK\""
            python3 - "$CORE_LAST_RESPONSE_FILE" "$out_dir" "$CORE_LAST_EXPORT_DIR_FILE" <<'PY'
import json, os, re, sys
from pathlib import Path

response_path, out_dir, export_marker = sys.argv[1:4]
payload = json.load(open(response_path, encoding="utf-8")).get("recorded_payload") or {}
output = str(payload.get("output") or "")
root = Path(out_dir).expanduser().resolve()
root.mkdir(parents=True, exist_ok=True)

def parse_section(name: str, text: str) -> str:
    pattern = re.compile(rf"(?ims)^\s*#+\s*{re.escape(name)}\s*$")
    matches = list(pattern.finditer(text))
    if not matches:
        return ""
    start = matches[0].end()
    rest = text[start:]
    next_header = re.search(r"(?ims)^\s*#+\s+[A-Za-z][^\n]*$", rest)
    return rest[: next_header.start() if next_header else len(rest)].strip()

def sanitize_relpath(path_text: str) -> str:
    path_text = path_text.strip().strip("`").strip()
    path_text = path_text.replace("\\", "/")
    path_text = re.sub(r"^\./", "", path_text)
    path_text = re.sub(r"/{2,}", "/", path_text)
    path_text = path_text.strip("/")
    if not path_text or path_text.startswith("..") or "/../" in f"/{path_text}/":
        raise ValueError(f"unsafe path: {path_text}")
    return path_text

complete_code = parse_section("Complete Code", output) or parse_section("Code", output)
file_tree = parse_section("File Tree", output)
stack = parse_section("Stack", output)
run_instructions = parse_section("Run Instructions", output)

written = []

if complete_code:
    code_pattern = re.compile(
        r"(?ms)^(?:\*\*|File:\s*|`{0,3})([^`\n*]+?\.[A-Za-z0-9._/-]+)(?:\*\*|`{0,3})\s*\n```[A-Za-z0-9_+-]*\n(.*?)\n```"
    )
    matches = list(code_pattern.finditer(complete_code))
    if matches:
        for match in matches:
            rel = sanitize_relpath(match.group(1))
            body = match.group(2)
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body.rstrip() + "\n", encoding="utf-8")
            written.append(rel)
    else:
        (root / "artifact.txt").write_text(output.rstrip() + "\n", encoding="utf-8")
        written.append("artifact.txt")
else:
    (root / "artifact.txt").write_text(output.rstrip() + "\n", encoding="utf-8")
    written.append("artifact.txt")

if file_tree:
    (root / "_meridian_file_tree.txt").write_text(file_tree.rstrip() + "\n", encoding="utf-8")
if stack:
    (root / "_meridian_stack.txt").write_text(stack.rstrip() + "\n", encoding="utf-8")
if run_instructions:
    (root / "_meridian_run_instructions.txt").write_text(run_instructions.rstrip() + "\n", encoding="utf-8")

manifest = {
    "source": response_path,
    "session_key": payload.get("session_key"),
    "written_files": written,
    "stack_present": bool(stack),
    "file_tree_present": bool(file_tree),
    "run_instructions_present": bool(run_instructions),
}
(root / "_meridian_export_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
Path(export_marker).write_text(str(root) + "\n", encoding="utf-8")
print(f"export_dir: {root}")
print(f"written_files: {len(written)}")
for item in written:
    print(f"- {item}")
PY
            ;;
        export-path)
            [ -f "$CORE_LAST_EXPORT_DIR_FILE" ] || die "No Core export captured yet. Run: ./scripts/core.sh response export OUT_DIR"
            cat "$CORE_LAST_EXPORT_DIR_FILE"
            ;;
        page)
            [ -f "$CORE_LAST_OUTPUT_FILE" ] || die "No Core response captured yet. Run: ./scripts/core.sh ask \"TASK\""
            "${PAGER:-less}" "$CORE_LAST_OUTPUT_FILE"
            ;;
        *)
            die "Usage: core.sh response <show|path|json|meta|export|export-path|page>"
            ;;
    esac
}

cmd_chat() {
    require_runtime
    ensure_core_state_dir
    local session_id
    session_id="$(resolve_core_session_id)"
    local -a pending_files=()
    cat <<EOF
[core] interactive chat
[core] session: $session_id
[core] commands: /exit /new [id] /use ID /current /show /response /file PATH /page /help
EOF
    while true; do
        local prompt_suffix=""
        if [ ${#pending_files[@]} -gt 0 ]; then
            prompt_suffix=" [${#pending_files[@]} file(s)]"
        fi
        printf 'core%s> ' "$prompt_suffix"
        IFS= read -r line || break
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        if [ -z "$line" ]; then
            continue
        fi
        case "$line" in
            /exit|/quit)
                break
                ;;
            /help)
                cat <<'EOF'
/exit              Exit interactive chat
/new [id]          Start a fresh current session
/use ID            Switch current session
/current           Show current session id
/show [id]         Show recent history for current or named session
/response          Show the last captured response
/file PATH         Attach a file to the next message
/attach PATH       Alias for /file
/files             Show pending attached files
/clear-files       Clear all pending file attachments
/page              Page through the last long output
/help              Show this help
EOF
                ;;
            /current)
                cmd_session current
                ;;
            /response)
                cmd_response meta
                echo ""
                cmd_response show
                ;;
            /new)
                cmd_session new
                session_id="$(resolve_core_session_id)"
                ;;
            /new\ *)
                cmd_session new "${line#"/new "}"
                session_id="$(resolve_core_session_id)"
                ;;
            /use\ *)
                cmd_session use "${line#"/use "}"
                session_id="$(resolve_core_session_id)"
                ;;
            /show)
                cmd_session show
                ;;
            /show\ *)
                cmd_session show "${line#"/show "}"
                ;;
            /file\ *|/attach\ *)
                local fpath="${line#*/file }"
                fpath="${fpath#*/attach }"
                fpath="${fpath#"${fpath%%[![:space:]]*}"}"
                fpath="${fpath%"${fpath##*[![:space:]]}"}"
                if [ -z "$fpath" ]; then
                    echo "[core] usage: /file PATH" >&2
                elif [ ! -f "$fpath" ]; then
                    echo "[core] file not found: $fpath" >&2
                else
                    pending_files+=("$fpath")
                    echo "[core] queued: $fpath (${#pending_files[@]} file(s) pending)"
                fi
                ;;
            /files)
                if [ ${#pending_files[@]} -eq 0 ]; then
                    echo "[core] no files pending"
                else
                    echo "[core] pending files:"
                    for f in "${pending_files[@]}"; do echo "  $f"; done
                fi
                ;;
            /clear-files|/clear)
                pending_files=()
                echo "[core] file queue cleared"
                ;;
            /page)
                if [ -f "$CORE_LAST_OUTPUT_FILE" ]; then
                    "${PAGER:-less}" "$CORE_LAST_OUTPUT_FILE"
                else
                    echo "[core] no output to page" >&2
                fi
                ;;
            /*)
                echo "[core] unknown chat command: $line" >&2
                ;;
            *)
                # Build file args if any are pending
                local -a ask_args=()
                for f in "${pending_files[@]}"; do
                    ask_args+=("--file" "$f")
                done
                ask_args+=("$line")
                cmd_ask "${ask_args[@]}"
                # Clear pending files after sending
                pending_files=()
                ;;
        esac
    done
}

cmd_doctor() {
    require_loom
    require_runtime

    local doctor_fix=""
    if [ "${1:-}" = "--fix" ] || [ "${1:-}" = "fix" ]; then
        doctor_fix="--fix"
    fi

    local personal_agent=""
    personal_agent="$(resolve_personal_agent_name)"

    echo "[core] runtime doctor"
    echo ""
    "$LOOM_BIN" doctor --root "$LOOM_ROOT" --format human $doctor_fix
    echo ""
    echo "[core] loom health"
    "$LOOM_BIN" health --root "$LOOM_ROOT" --format human
    echo ""
    echo "[core] provider status"
    "$LOOM_BIN" provider status --root "$LOOM_ROOT" --format human
    echo ""
    echo "[core] gateway status"
    "$LOOM_BIN" gateway status --root "$LOOM_ROOT" --format human
    echo ""
    echo "[core] queue status"
    "$LOOM_BIN" queue status --root "$LOOM_ROOT" --format human
    echo ""
    echo "[core] memory status"
    "$LOOM_BIN" memory status --root "$LOOM_ROOT" --format human
    if [ -n "$personal_agent" ]; then
        echo ""
        echo "[core] agent diagnose ($personal_agent)"
        "$LOOM_BIN" run-agent diagnose "$personal_agent" --root "$LOOM_ROOT" --format human
        echo ""
        echo "[core] channel health ($personal_agent)"
        "$LOOM_BIN" channel health --root "$LOOM_ROOT" --agent "$personal_agent" --format human
    fi
}

cmd_provider() {
    local subcmd="${1:-status}"
    shift || true
    require_loom
    require_runtime

    case "$subcmd" in
        status)
            "$LOOM_BIN" provider status --root "$LOOM_ROOT" --format human "${@}"
            ;;
        profiles)
            "$LOOM_BIN" provider profiles --root "$LOOM_ROOT" --format human "${@}"
            ;;
        auth)
            "$LOOM_BIN" provider auth --root "$LOOM_ROOT" --format human "${@}"
            ;;
        route)
            "$LOOM_BIN" provider route --root "$LOOM_ROOT" --format human "${@}"
            ;;
        login)
            "$LOOM_BIN" provider login --root "$LOOM_ROOT" "${@}"
            ;;
        *)
            die "Usage: core.sh provider <status|profiles|auth|route|login> [args]"
            ;;
    esac
}

cmd_config() {
    local subcmd="${1:-show}"
    shift || true
    require_loom
    require_runtime

    case "$subcmd" in
        show)
            "$LOOM_BIN" config show --root "$LOOM_ROOT" "${@}"
            ;;
        *)
            die "Usage: core.sh config <show> [args]"
            ;;
    esac
}

cmd_runtime() {
    local subcmd="${1:-status}"
    shift || true
    require_loom
    require_runtime

    case "$subcmd" in
        status)
            "$LOOM_BIN" status --root "$LOOM_ROOT" "${@}"
            ;;
        logs)
            "$LOOM_BIN" logs --root "$LOOM_ROOT" "${@}"
            ;;
        health)
            "$LOOM_BIN" health --root "$LOOM_ROOT" --format human "${@}"
            ;;
        *)
            die "Usage: core.sh runtime <status|logs|health> [args]"
            ;;
    esac
}

cmd_session() {
    local subcmd="${1:-current}"
    shift || true
    require_runtime
    ensure_core_state_dir

    case "$subcmd" in
        current)
            local current
            current="$(resolve_core_session_id)"
            echo "$current"
            ;;
        use)
            local requested="${1:-}"
            [ -n "$requested" ] || die "Usage: core.sh session use SESSION_ID"
            local session_id
            session_id="$(normalize_core_session_id "$requested")"
            [ -n "$session_id" ] || die "Session id is empty after normalization."
            write_current_core_session_id "$session_id"
            register_core_session "$session_id"
            echo "[core] current session: $session_id"
            ;;
        new)
            local requested="${1:-}"
            local session_id
            if [ -n "$requested" ]; then
                session_id="$(normalize_core_session_id "$requested")"
            else
                session_id="$(generate_core_session_id)"
            fi
            [ -n "$session_id" ] || die "Could not create session id."
            write_current_core_session_id "$session_id"
            register_core_session "$session_id"
            echo "[core] new session: $session_id"
            ;;
        list)
            local limit="${1:-20}"
            python3 - "$CORE_SESSION_REGISTRY_FILE" "$CORE_CURRENT_SESSION_FILE" "$limit" <<'PY'
import json, os, sys
registry_path, current_path, limit = sys.argv[1], sys.argv[2], int(sys.argv[3] or "20")
current = ""
if os.path.exists(current_path):
    try:
        current = str(json.load(open(current_path, encoding="utf-8")).get("session_id") or "").strip()
    except Exception:
        current = ""
data = {"sessions": {}}
if os.path.exists(registry_path):
    try:
        data = json.load(open(registry_path, encoding="utf-8"))
    except Exception:
        data = {"sessions": {}}
sessions = list((data.get("sessions") or {}).values())
sessions.sort(key=lambda item: int(item.get("last_used_unix_ms") or 0), reverse=True)
if not sessions:
    print("[core] no tracked core sessions yet")
    raise SystemExit(0)
print("[core] tracked sessions:")
for entry in sessions[:limit]:
    sid = str(entry.get("session_id") or "").strip()
    marker = "*" if sid == current else " "
    last_used = int(entry.get("last_used_unix_ms") or 0)
    print(f"{marker} {sid}  last_used={last_used}")
PY
            ;;
        show)
            local requested="${1:-}"
            local session_id
            if [ -n "$requested" ]; then
                session_id="$(normalize_core_session_id "$requested")"
            else
                session_id="$(resolve_core_session_id)"
            fi
            python3 - "$LOOM_ROOT" "$session_id" <<'PY'
import glob, json, os, sys
loom_root, session_id = sys.argv[1], sys.argv[2]
session_key = f"web_api:{session_id}"
paths = sorted(glob.glob(os.path.join(loom_root, "state", "session-history", "events", "*.json")), key=os.path.getmtime, reverse=True)
for path in paths:
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    if str(data.get("session_key") or "").strip() != session_key:
        continue
    events = data.get("events") or []
    print(f"session_key: {session_key}")
    print(f"updated_at: {data.get('updated_at') or ''}")
    print(f"event_count: {len(events)}")
    print("")
    for event in events[-12:]:
        history_type = str(event.get("history_type") or "").strip()
        status = str(event.get("status") or "").strip()
        text = str(event.get("text") or "").strip().replace("\n", " ")
        if len(text) > 220:
            text = text[:217] + "..."
        print(f"- {history_type} [{status}]: {text}")
    raise SystemExit(0)
print(f"[core] no session history found for web_api:{session_id}")
PY
            ;;
        export)
            local session_arg="${1:-}"
            local out_dir="${2:-}"
            local session_id
            if [ -n "$out_dir" ]; then
                session_id="$(normalize_core_session_id "$session_arg")"
            else
                out_dir="$session_arg"
                session_id="$(resolve_core_session_id)"
            fi
            [ -n "$out_dir" ] || die "Usage: core.sh session export [SESSION_ID] OUT_DIR"
            [ -n "$session_id" ] || session_id="$(resolve_core_session_id)"
            python3 - "$LOOM_ROOT" "$session_id" "$out_dir" <<'PY'
import glob, json, os, sys
from pathlib import Path

loom_root, session_id, out_dir = sys.argv[1:4]
session_key = f"web_api:{session_id}"
paths = sorted(
    glob.glob(os.path.join(loom_root, "state", "session-history", "events", "*.json")),
    key=os.path.getmtime,
    reverse=True,
)
payload = None
for path in paths:
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    if str(data.get("session_key") or "").strip() == session_key:
        payload = data
        break

if payload is None:
    print(f"[core] no session history found for {session_key}", file=sys.stderr)
    raise SystemExit(1)

root = Path(out_dir).expanduser().resolve()
root.mkdir(parents=True, exist_ok=True)

events = list(payload.get("events") or [])
manifest = {
    "session_id": session_id,
    "session_key": session_key,
    "updated_at": payload.get("updated_at"),
    "event_count": len(events),
    "source_live": bool(payload.get("live")),
    "source_path": str(Path(path).resolve()) if 'path' in locals() else "",
}

(root / "session.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
(root / "_meridian_session_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

lines = [f"# Meridian Session Export", "", f"- session_id: `{session_id}`", f"- session_key: `{session_key}`", f"- updated_at: `{payload.get('updated_at') or ''}`", f"- event_count: `{len(events)}`", ""]
for event in events:
    history_type = str(event.get("history_type") or "").strip()
    status = str(event.get("status") or "").strip()
    speaker = str(event.get("speaker") or "").strip() or "system"
    text = str(event.get("text") or "").strip()
    lines.append(f"## {history_type} [{status}]")
    lines.append(f"- speaker: `{speaker}`")
    if text:
        lines.append("")
        lines.append(text)
    lines.append("")

(root / "session.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
print(f"export_dir: {root}")
print(f"session_key: {session_key}")
print(f"event_count: {len(events)}")
print("- session.json")
print("- session.md")
print("- _meridian_session_manifest.json")
PY
            ;;
        reset)
            rm -f "$CORE_CURRENT_SESSION_FILE"
            echo "[core] current session reset"
            ;;
        *)
            die "Usage: core.sh session <current|use|new|list|show|export|reset> [args]"
            ;;
    esac
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

# ── Command: agent ────────────────────────────────────────────────────────

cmd_agent() {
    local subcmd="${1:-inspect}"
    shift || true
    require_loom; require_runtime

    local agent_id; agent_id="$(resolve_agent_id)"
    local personal_agent; personal_agent="$(resolve_personal_agent_name)"
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    case "$subcmd" in
        inspect)
            [ -n "$personal_agent" ] || die "Could not resolve personal agent name for run-agent inspect."
            "$LOOM_BIN" run-agent inspect "$personal_agent" --root "$LOOM_ROOT" "${@}"
            ;;
        diagnose)
            [ -n "$personal_agent" ] || die "Could not resolve personal agent name for run-agent diagnose."
            "$LOOM_BIN" run-agent diagnose "$personal_agent" --root "$LOOM_ROOT" "${@}"
            ;;
        status)
            [ -n "$personal_agent" ] || die "Could not resolve personal agent name for run-agent status."
            "$LOOM_BIN" run-agent status "$personal_agent" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        session)
            "$LOOM_BIN" agent session --agent-id "$agent_id" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        context)
            "$LOOM_BIN" agent context --agent-id "$agent_id" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        memory)
            "$LOOM_BIN" agent memory --agent-id "$agent_id" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        *)
            die "Usage: core.sh agent <inspect|diagnose|status|session|context|memory> [args]"
            ;;
    esac
}

# ── Command: job ──────────────────────────────────────────────────────────

cmd_job() {
    local subcmd="${1:-list}"
    shift || true
    require_loom; require_runtime

    case "$subcmd" in
        list)
            "$LOOM_BIN" job list --root "$LOOM_ROOT" --format human "${@}"
            ;;
        inspect)
            local job_id="${1:-}"
            [ -n "$job_id" ] || die "Usage: core.sh job inspect JOB_ID"
            shift || true
            "$LOOM_BIN" job inspect --job-id "$job_id" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        approve)
            local job_id="${1:-}"
            [ -n "$job_id" ] || die "Usage: core.sh job approve JOB_ID"
            shift || true
            "$LOOM_BIN" job approve --job-id "$job_id" --root "$LOOM_ROOT" "${@}"
            ;;
        *)
            die "Usage: core.sh job <list|inspect|approve> [args]"
            ;;
    esac
}

# ── Command: channel ──────────────────────────────────────────────────────

cmd_channel() {
    local subcmd="${1:-health}"
    shift || true
    require_loom; require_runtime

    local personal_agent; personal_agent="$(resolve_personal_agent_name)"
    [ -n "$personal_agent" ] || die "Could not resolve personal agent name. Run onboard.sh first."

    case "$subcmd" in
        list)
            "$LOOM_BIN" channel list --root "$LOOM_ROOT" --agent "$personal_agent" --format human "${@}"
            ;;
        health)
            "$LOOM_BIN" channel health --root "$LOOM_ROOT" --agent "$personal_agent" --format human "${@}"
            ;;
        show)
            "$LOOM_BIN" channel show --agent "$personal_agent" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        deliveries)
            "$LOOM_BIN" channel deliveries --root "$LOOM_ROOT" --include-archived --format human "${@}"
            ;;
        send)
            local channel_id="${1:-}"; local recipient="${2:-}"; shift 2 || true
            local text="${*:-}"
            [ -n "$channel_id" ] && [ -n "$recipient" ] && [ -n "$text" ] || die "Usage: core.sh channel send CHANNEL RECIPIENT TEXT"
            "$LOOM_BIN" channel send --channel "$channel_id" --recipient "$recipient" --text "$text" --root "$LOOM_ROOT" --format human
            ;;
        test)
            "$LOOM_BIN" channel test --agent "$personal_agent" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        *)
            die "Usage: core.sh channel <list|health|show|deliveries|send|test> [args]"
            ;;
    esac
}

# ── Command: queue ────────────────────────────────────────────────────────

cmd_queue() {
    local subcmd="${1:-status}"
    shift || true
    require_loom; require_runtime

    case "$subcmd" in
        status)
            "$LOOM_BIN" queue status --root "$LOOM_ROOT" --format human "${@}"
            ;;
        inspect)
            "$LOOM_BIN" queue inspect --root "$LOOM_ROOT" --format human "${@}"
            ;;
        run-once)
            "$LOOM_BIN" queue run-once --root "$LOOM_ROOT" --format human "${@}"
            ;;
        run-until-empty)
            "$LOOM_BIN" queue run-until-empty --root "$LOOM_ROOT" --format human "${@}"
            ;;
        *)
            die "Usage: core.sh queue <status|inspect|run-once|run-until-empty> [args]"
            ;;
    esac
}

# ── Command: memory ───────────────────────────────────────────────────────

cmd_memory() {
    local subcmd="${1:-receipts}"
    shift || true
    require_loom; require_runtime

    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    case "$subcmd" in
        receipts)
            "$LOOM_BIN" memory receipts --agent-id "$agent_id" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        graph)
            local source_ref="${1:-}"
            [ -n "$source_ref" ] || die "Usage: core.sh memory graph SOURCE_REF [--node-id ID ...]"
            shift || true
            "$LOOM_BIN" memory graph inspect "$source_ref" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        overview)
            "$LOOM_BIN" memory overview --root "$LOOM_ROOT" --format human "${@}"
            ;;
        status)
            "$LOOM_BIN" memory status --root "$LOOM_ROOT" --format human "${@}"
            ;;
        *)
            die "Usage: core.sh memory <receipts|graph|overview|status> [args]"
            ;;
    esac
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
  ask [--file PATH ...] "TASK"   Run a daily prompt (with optional file attachments)
  session current        Show the current Core conversation session id
  session new [ID]       Start a fresh Core session and make it current
  session use ID         Switch the current Core session
  session list           List tracked Core sessions
  session show [ID]      Show recent history for a Core session
  session export [ID] D  Export a Core session to JSON + Markdown in directory D
  session reset          Clear the current Core session pointer
  response show          Show the most recent Core ask output
  response meta          Show route/session metadata for the last Core ask
  response path          Show the JSON receipt path for the last Core ask
  response page          Page through last response (useful for long outputs)
  response export DIR    Export the most recent Core artifact into DIR
  response export-path   Show the last Core export directory
  chat                   Start an interactive Core chat loop on the current session
  doctor [--fix]         Run the Core operator doctor across runtime/provider/gateway/channel surfaces
  provider status        Show configured provider plane status
  provider profiles      Show provider profiles
  provider auth          Show provider auth readiness
  provider route ...     Inspect provider route decisions
  config show            Show effective runtime config
  runtime status         Show loom runtime status
  runtime health         Show loom doctor-derived health summary
  runtime logs           Show recent loom runtime logs
  browse URL               Navigate to URL, extract and show text
  research "cmd [args]"   Run a bounded terminal command
  remember KEY "VALUE"    Store a memory entry (persistent across sessions)
  recall [KEY_PREFIX]     Search stored memory
  memory receipts         Show recent memory receipts
  memory graph SOURCE_REF Inspect memory graph lineage/forks
  memory overview         Show memory overview
  schedule NAME [SEC]     Add a recurring task (default: every 3600s)
  schedules               List all scheduled tasks
  agent inspect           Show live agent/operator state
  agent diagnose          Show remediation plan from live state
  agent status            Show loop status
  job list                List recent runtime jobs
  job inspect JOB_ID      Inspect a runtime job receipt
  channel health          Show channel health for the current agent
  channel deliveries      Show recent outbound delivery ledger
  channel send CH R TXT   Send text to a named channel/recipient
  queue status            Show queue depth/state
  queue inspect           Inspect queued records
  inspect                 Show last execution receipts and agent state
  status                  Show full runtime status
  cap list                List available capabilities
  cap inspect NAME        Show capability metadata
  cap run NAME [PAYLOAD]  Run a capability by name
  help                    Show this help

File attachments:
  core.sh ask --file src/main.py "review this code"
  core.sh ask -f a.py -f b.py "compare these two files"
  In chat mode: /file PATH to queue, then type your message

Long output handling:
  Long responses are auto-truncated with a preview.
  Use: core.sh response page    to page through the full output
  Use: core.sh response export DIR   to save as files

Capability contributor flow:
  ./scripts/skill.sh scaffold my.cap.v1
  ./scripts/skill.sh verify my.cap.v1
  ./scripts/skill.sh promote my.cap.v1
  ./scripts/core.sh cap run my.cap.v1

Environment:
  MERIDIAN_ROOT      monorepo root (default: auto-detected)
  MERIDIAN_LOOM_ROOT loom runtime root (default: runtime/default)
  MERIDIAN_GATEWAY_URL local gateway base URL (default: http://127.0.0.1:8266)
  MERIDIAN_ORG_ID    org id override
  MERIDIAN_AGENT_ID  agent id override
  MERIDIAN_SESSION_ID explicit session id override for core.sh ask/session
  MERIDIAN_CORE_LONG_OUTPUT_CHARS  char threshold for auto-truncation (default: 4000)
  MERIDIAN_CORE_LONG_OUTPUT_LINES  line threshold for auto-truncation (default: 80)

First time:
  ./scripts/onboard.sh          interactive setup
  ./scripts/onboard.sh --mode core  quick Core setup with defaults
EOF
}

# ── Main dispatch ─────────────────────────────────────────────────────────

COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
    ask)         cmd_ask "$@" ;;
    session)     cmd_session "$@" ;;
    response)    cmd_response "$@" ;;
    chat)        cmd_chat "$@" ;;
    doctor)      cmd_doctor "$@" ;;
    provider)    cmd_provider "$@" ;;
    config)      cmd_config "$@" ;;
    runtime)     cmd_runtime "$@" ;;
    browse)      cmd_browse "$@" ;;
    research)    cmd_research "$@" ;;
    remember)    cmd_remember "$@" ;;
    recall)      cmd_recall "$@" ;;
    schedule)    cmd_schedule "$@" ;;
    schedules)   cmd_schedules "$@" ;;
    memory)      cmd_memory "$@" ;;
    agent)       cmd_agent "$@" ;;
    job)         cmd_job "$@" ;;
    channel)     cmd_channel "$@" ;;
    queue)       cmd_queue "$@" ;;
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
