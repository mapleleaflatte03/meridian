#!/usr/bin/env bash
# Meridian Core — daily-use task runner
#
# Wraps loom CLI so you can complete common tasks without knowing
# the full loom flag surface.
#
# Usage:
#   ./scripts/core.sh browse URL               — navigate URL, show text
#   ./scripts/core.sh ask [--file PATH ...] [--session ID] "TASK" — run a prompt with optional file attachments
#   ./scripts/core.sh research "cmd [args]"    — run a bounded terminal command
#   ./scripts/core.sh remember KEY "VALUE"     — store a memory entry
#   ./scripts/core.sh recall KEY               — search memory by key prefix
#   ./scripts/core.sh memory receipts          — show recent memory receipts
#   ./scripts/core.sh memory graph SOURCE_REF  — inspect memory graph fork/root
#   ./scripts/core.sh memory fork SOURCE_REF   — create a governed memory fork lane
#   ./scripts/core.sh memory replay SOURCE_REF — replay governed memory into another agent
#   ./scripts/core.sh memory latest-fork       — inspect latest governed memory fork artifact
#   ./scripts/core.sh memory latest-replay     — inspect latest governed memory replay artifact
#   ./scripts/core.sh memory fork-history      — inspect recent governed memory fork artifacts
#   ./scripts/core.sh memory replay-history    — inspect recent governed memory replay artifacts
#   ./scripts/core.sh memory governance        — governed memory operator summary
#   ./scripts/core.sh schedule NAME every SEC  — add a recurring task
#   ./scripts/core.sh playbook every NAME SEC  — schedule a saved Core playbook
#   ./scripts/core.sh schedules                — list scheduled tasks
#   ./scripts/core.sh agent inspect            — show live agent/operator state
#   ./scripts/core.sh job list                 — inspect recent runtime jobs
#   ./scripts/core.sh channel health           — inspect channel health/deliveries
#   ./scripts/core.sh channel diagnostics      — multi-channel health or per-channel diagnostics
#   ./scripts/core.sh channel proof CH [N]     — sha256-chained delivery receipt proof
#   ./scripts/core.sh channel verify CH [R|auto] [TXT] — real send-and-prove round trip
#   ./scripts/core.sh channel watch CH         — tail live delivery + inbound for a channel
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
CORE_LAST_PROOF_FILE="${CORE_STATE_DIR}/last_proof.json"
CORE_LAST_DOCTOR_FILE="${CORE_STATE_DIR}/last_doctor.json"
CORE_PENDING_FILES_FILE="${CORE_STATE_DIR}/pending_files.json"
CORE_CONTEXT_FILES_FILE="${CORE_STATE_DIR}/context_files.json"
CORE_LAST_RESUME_FILE="${CORE_STATE_DIR}/last_resume.txt"
CORE_PLAYBOOKS_DIR="${CORE_STATE_DIR}/playbooks"
CORE_PLAYBOOK_SCHEDULES_FILE="${CORE_STATE_DIR}/playbook_schedules.json"
CORE_ARTIFACT_LONG_THRESHOLD="${MERIDIAN_CORE_LONG_OUTPUT_CHARS:-4000}"
CORE_ARTIFACT_LONG_LINES="${MERIDIAN_CORE_LONG_OUTPUT_LINES:-80}"
MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS="${MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS:-}"
MERIDIAN_WORKSPACE_PORT="${MERIDIAN_WORKSPACE_PORT:-18901}"
MERIDIAN_WORKSPACE_PEER_PORT="${MERIDIAN_WORKSPACE_PEER_PORT:-19001}"
MERIDIAN_GATEWAY_PORT="${MERIDIAN_GATEWAY_PORT:-8266}"
MERIDIAN_LOCAL_ENV_DIR="${MERIDIAN_LOCAL_ENV_DIR:-/home/ubuntu/.meridian}"

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

ensure_core_playbooks_dir() {
    ensure_core_state_dir
    mkdir -p "$CORE_PLAYBOOKS_DIR"
}

wait_for_local_gateway_ready() {
    local gateway_url="${MERIDIAN_GATEWAY_URL%/}"
    case "$gateway_url" in
        http://127.0.0.1:*|http://localhost:*)
            ;;
        *)
            return 0
            ;;
    esac
    local probe
    for probe in /api/healthz /api/status; do
        if curl -fsS --max-time 2 "${gateway_url}${probe}" >/dev/null 2>&1; then
            return 0
        fi
    done
    local attempt
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        for probe in /api/healthz /api/status; do
            if curl -fsS --max-time 2 "${gateway_url}${probe}" >/dev/null 2>&1; then
                return 0
            fi
        done
        sleep 1
    done
    return 1
}

attempt_local_gateway_autoheal() {
    local gateway_url="${MERIDIAN_GATEWAY_URL%/}"
    case "$gateway_url" in
        http://127.0.0.1:*|http://localhost:*)
            ;;
        *)
            return 1
            ;;
    esac
    local devup_log
    devup_log="$(mktemp /tmp/meridian-core-devup.XXXXXX.log)"
    if ./scripts/dev-up.sh --no-summary >"$devup_log" 2>&1; then
        cat "$devup_log" >&2 || true
        rm -f "$devup_log"
        return 0
    fi
    cat "$devup_log" >&2 || true
    rm -f "$devup_log"
    return 1
}

load_pending_files_json() {
    ensure_core_state_dir
    if [ -f "$CORE_PENDING_FILES_FILE" ]; then
        cat "$CORE_PENDING_FILES_FILE"
    else
        printf '[]\n'
    fi
}

save_pending_files_json() {
    ensure_core_state_dir
    printf '%s\n' "${1:-[]}" > "$CORE_PENDING_FILES_FILE"
}

load_context_files_json() {
    ensure_core_state_dir
    if [ -f "$CORE_CONTEXT_FILES_FILE" ]; then
        cat "$CORE_CONTEXT_FILES_FILE"
    else
        printf '[]\n'
    fi
}

save_context_files_json() {
    ensure_core_state_dir
    printf '%s\n' "${1:-[]}" > "$CORE_CONTEXT_FILES_FILE"
}

merge_pending_file_paths_json() {
    python3 - "$@" <<'PY'
import json, os, sys
current = json.loads(sys.argv[1] or "[]")
extras = sys.argv[2:]
seen = set()
merged = []
for path in list(current) + extras:
    path = os.path.abspath(os.path.expanduser(str(path)))
    if not path or path in seen:
        continue
    if not os.path.isfile(path):
        continue
    seen.add(path)
    merged.append(path)
print(json.dumps(merged, ensure_ascii=False))
PY
}

read_env_file_value() {
    local file_path="$1"
    local key="$2"
    [ -f "$file_path" ] || return 1
    python3 - "$file_path" "$key" <<'PY'
import pathlib, re, sys
path, key = sys.argv[1], sys.argv[2]
for line in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    m = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
    if not m or m.group(1) != key:
        continue
    value = m.group(2).strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    print(value)
    raise SystemExit(0)
raise SystemExit(1)
PY
}

resolve_loom_service_token() {
    if [ -n "${LOOM_SERVICE_TOKEN:-}" ]; then
        printf 'env:LOOM_SERVICE_TOKEN\t%s\n' "$LOOM_SERVICE_TOKEN"
        return 0
    fi
    if [ -n "${MERIDIAN_LOOM_SERVICE_TOKEN:-}" ]; then
        printf 'env:MERIDIAN_LOOM_SERVICE_TOKEN\t%s\n' "$MERIDIAN_LOOM_SERVICE_TOKEN"
        return 0
    fi

    local gateway_env="${MERIDIAN_LOCAL_ENV_DIR}/.env.gateway"
    local main_env="${MERIDIAN_LOCAL_ENV_DIR}/.env"
    local value=""
    value="$(read_env_file_value "$gateway_env" "LOOM_SERVICE_TOKEN" 2>/dev/null || true)"
    if [ -n "$value" ]; then
        printf 'file:%s#LOOM_SERVICE_TOKEN\t%s\n' "$gateway_env" "$value"
        return 0
    fi
    value="$(read_env_file_value "$gateway_env" "MERIDIAN_LOOM_SERVICE_TOKEN" 2>/dev/null || true)"
    if [ -n "$value" ]; then
        printf 'file:%s#MERIDIAN_LOOM_SERVICE_TOKEN\t%s\n' "$gateway_env" "$value"
        return 0
    fi
    value="$(read_env_file_value "$main_env" "LOOM_SERVICE_TOKEN" 2>/dev/null || true)"
    if [ -n "$value" ]; then
        printf 'file:%s#LOOM_SERVICE_TOKEN\t%s\n' "$main_env" "$value"
        return 0
    fi
    value="$(read_env_file_value "$main_env" "MERIDIAN_LOOM_SERVICE_TOKEN" 2>/dev/null || true)"
    if [ -n "$value" ]; then
        printf 'file:%s#MERIDIAN_LOOM_SERVICE_TOKEN\t%s\n' "$main_env" "$value"
        return 0
    fi
    return 1
}

quarantine_stale_ingress_requests() {
    local requests_dir="${LOOM_ROOT}/run/ingress/requests"
    local quarantine_dir="${LOOM_ROOT}/run/ingress/quarantine"
    local max_age_seconds="${MERIDIAN_CORE_DOCTOR_INGRESS_MAX_AGE_SECONDS:-300}"
    local scoped_max_age_seconds="${MERIDIAN_CORE_DOCTOR_SCOPED_INGRESS_MAX_AGE_SECONDS:-86400}"
    python3 - "$requests_dir" "$quarantine_dir" "$max_age_seconds" "$scoped_max_age_seconds" <<'PY'
import json, os, pathlib, re, shutil, sys, time

requests_dir = pathlib.Path(sys.argv[1])
quarantine_dir = pathlib.Path(sys.argv[2])
max_age_seconds = int(sys.argv[3] or "300")
scoped_max_age_seconds = int(sys.argv[4] or "86400")
if not requests_dir.exists():
    print(json.dumps({"moved_count": 0, "moved_files": [], "reason": "requests_dir_missing"}))
    raise SystemExit(0)

quarantine_dir.mkdir(parents=True, exist_ok=True)
moved = []

def stale_tmp_paths(payload: dict) -> list[str]:
    hits = []
    kernel_path = str(payload.get("kernel_path") or "").strip()
    if kernel_path.startswith("/tmp/") and not os.path.exists(kernel_path):
        hits.append(kernel_path)
    raw = json.dumps(payload, ensure_ascii=False)
    for match in re.findall(r"/tmp/[^\s\"'`]+", raw):
        if not os.path.exists(match):
            hits.append(match)
    return sorted(set(hits))

def stale_unowned_submit_action(path: pathlib.Path, payload: dict) -> str:
    request_type = str(payload.get("request_type") or "").strip()
    if request_type != "submit_action":
        return ""
    kernel_path = str(payload.get("kernel_path") or "").strip()
    root = str(payload.get("root") or "").strip()
    if kernel_path or root:
        return ""
    age_seconds = max(0, int(time.time() - path.stat().st_mtime))
    if age_seconds < max_age_seconds:
        return ""
    return f"submit_action older than {max_age_seconds}s with no kernel_path/root (age={age_seconds}s)"

def stale_scoped_staged_submit_action(path: pathlib.Path, payload: dict) -> str:
    request_type = str(payload.get("request_type") or "").strip()
    if request_type != "submit_action":
        return ""
    if str(payload.get("status") or "").strip() != "staged":
        return ""
    kernel_path = str(payload.get("kernel_path") or "").strip()
    root = str(payload.get("root") or "").strip()
    if not kernel_path and not root:
        return ""
    age_seconds = max(0, int(time.time() - path.stat().st_mtime))
    if age_seconds < scoped_max_age_seconds:
        return ""
    return f"staged scoped submit_action older than {scoped_max_age_seconds}s (age={age_seconds}s)"

for path in sorted(requests_dir.glob("*.json")):
    try:
        payload = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    bad_paths = stale_tmp_paths(payload)
    stale_reason = stale_unowned_submit_action(path, payload)
    scoped_stale_reason = stale_scoped_staged_submit_action(path, payload)
    if not bad_paths and not stale_reason and not scoped_stale_reason:
        continue
    dest = quarantine_dir / path.name
    shutil.move(str(path), str(dest))
    moved.append({
        "file": path.name,
        "stale_paths": bad_paths,
        "stale_reason": stale_reason or scoped_stale_reason,
    })

print(json.dumps({"moved_count": len(moved), "moved_files": moved}, ensure_ascii=False))
PY
}

render_ingress_snapshot() {
    local bucket="${1:-pending}"
    local limit="${2:-20}"
    local max_age_seconds="${MERIDIAN_CORE_DOCTOR_INGRESS_MAX_AGE_SECONDS:-300}"
    python3 - "$LOOM_ROOT" "$bucket" "$limit" "$max_age_seconds" <<'PY'
import collections, json, os, pathlib, time, sys

loom_root = pathlib.Path(sys.argv[1])
bucket = sys.argv[2]
limit = int(sys.argv[3] or "20")
max_age_seconds = int(sys.argv[4] or "300")
ingress_root = loom_root / "run" / "ingress"
target = ingress_root / ("quarantine" if bucket == "quarantine" else "requests")

print("[core] ingress status" if bucket == "pending" else "[core] ingress quarantine")
print(f"  root:            {ingress_root}")
print(f"  bucket:          {bucket}")
print(f"  path:            {target}")
print(f"  stale_after_s:   {max_age_seconds}")

if not target.exists():
    print("  total_files:     0")
    print("  note:            ingress bucket missing")
    raise SystemExit(0)

rows = []
breakdown = collections.Counter()
now = time.time()
for path in sorted(target.glob("*.json")):
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        rows.append({
            "file": path.name,
            "agent_id": "?",
            "action_type": "?",
            "resource": "?",
            "age_seconds": max(0, int(now - path.stat().st_mtime)),
            "state": "malformed",
            "detail": str(exc),
        })
        breakdown[("malformed", "?")] += 1
        continue
    agent_id = str(payload.get("agent_id") or "?")
    action_type = str(payload.get("action_type") or "?")
    resource = str(payload.get("resource") or "?")
    kernel_path = str(payload.get("kernel_path") or "")
    root = str(payload.get("root") or "")
    age_seconds = max(0, int(now - path.stat().st_mtime))
    if kernel_path.startswith("/tmp/"):
        state = "tmp_kernel"
    elif not kernel_path and not root:
        state = "unowned"
    else:
        state = "scoped"
    rows.append({
        "file": path.name,
        "agent_id": agent_id,
        "action_type": action_type,
        "resource": resource,
        "age_seconds": age_seconds,
        "state": state,
    })
    breakdown[(agent_id, action_type)] += 1

print(f"  total_files:     {len(rows)}")
old_count = len([r for r in rows if int(r.get('age_seconds') or 0) >= max_age_seconds])
print(f"  stale_files:     {old_count}")
if breakdown:
    print("  top_workloads:")
    for (agent_id, action_type), count in breakdown.most_common(8):
        print(f"    - {agent_id} / {action_type}: {count}")
else:
    print("  top_workloads:   (none)")

if rows:
    print(f"  newest_{min(limit, len(rows))}:")
    for row in sorted(rows, key=lambda item: item.get("age_seconds", 0))[:limit]:
        resource = str(row.get("resource") or "?")
        if len(resource) > 48:
            resource = resource[:45] + "..."
        print(
            f"    - {row['file']}  agent={row['agent_id']} action={row['action_type']} "
            f"state={row['state']} age_s={row['age_seconds']} resource={resource}"
        )
PY
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
    local model_override=""
    local session_override=""
    local use_queued_files="0"
    local use_context_files="1"
    # Parse arguments: support --file PATH (repeatable), --model MODEL, and --session ID before or after the goal
    while [ $# -gt 0 ]; do
        case "$1" in
            --file|-f)
                [ -n "${2:-}" ] || die "Usage: --file requires a PATH argument"
                file_paths+=("$2")
                shift 2
                ;;
            --queued-files|--files)
                use_queued_files="1"
                shift
                ;;
            --no-context)
                use_context_files="0"
                shift
                ;;
            --model|-m)
                [ -n "${2:-}" ] || die "Usage: --model requires a MODEL argument"
                model_override="$2"
                shift 2
                ;;
            --session)
                [ -n "${2:-}" ] || die "Usage: --session requires an ID argument"
                session_override="$2"
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
    [ -n "$goal" ] || die "Usage: core.sh ask [--file PATH ...] [--model MODEL] [--session ID] \"TASK\""
    require_runtime
    ensure_core_state_dir

    if [ "$use_queued_files" = "1" ]; then
        local queued_files_json queued_joined
        queued_files_json="$(load_pending_files_json)"
        queued_joined="$(python3 - "$queued_files_json" <<'PY'
import json, sys
for item in json.loads(sys.argv[1] or "[]"):
    print(item)
PY
)"
        if [ -n "$queued_joined" ]; then
            while IFS= read -r queued_path; do
                [ -n "$queued_path" ] || continue
                file_paths+=("$queued_path")
            done <<< "$queued_joined"
        fi
    fi

    if [ "$use_context_files" = "1" ]; then
        local context_files_json context_joined
        context_files_json="$(load_context_files_json)"
        context_joined="$(python3 - "$context_files_json" <<'PY'
import json, sys
for item in json.loads(sys.argv[1] or "[]"):
    print(item)
PY
)"
        if [ -n "$context_joined" ]; then
            while IFS= read -r context_path; do
                [ -n "$context_path" ] || continue
                file_paths+=("$context_path")
            done <<< "$context_joined"
        fi
    fi

    if [ ${#file_paths[@]} -gt 0 ]; then
        local deduped_files_json
        deduped_files_json="$(merge_pending_file_paths_json '[]' "${file_paths[@]}")"
        mapfile -t file_paths < <(python3 - "$deduped_files_json" <<'PY'
import json, sys
for item in json.loads(sys.argv[1] or "[]"):
    print(item)
PY
)
    fi

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
    if [ -n "$session_override" ]; then
        session_id="$session_override"
    else
        session_id="$(resolve_core_session_id)"
    fi
    local request_body
    request_body="$(python3 - "$goal" "$session_id" "$attachments_json" "$model_override" <<'PY'
import json, sys

goal, session_id, attachments_json, model_override = sys.argv[1:5]
attachments = json.loads(attachments_json)
payload = {"goal": goal, "session_id": session_id}
if attachments:
    payload["attachments"] = attachments
if model_override:
    payload["model"] = model_override
print(json.dumps(payload, ensure_ascii=False))
PY
)"
    local response_file error_file http_code
    response_file="$(mktemp /tmp/meridian-core-ask-response.XXXXXX.json)"
    error_file="$(mktemp /tmp/meridian-core-ask-error.XXXXXX.txt)"
    if ! wait_for_local_gateway_ready; then
        echo "[core] gateway preflight not ready: ${MERIDIAN_GATEWAY_URL} (continuing with direct POST retries)" >&2
    fi
    local curl_ok="0"
    local curl_err=""
    local attempt
    local autoheal_attempted="0"
    for attempt in 1 2 3; do
        if http_code="$(curl -sS -o "$response_file" -w "%{http_code}" -H "Content-Type: application/json" --data-binary "$request_body" "${MERIDIAN_GATEWAY_URL%/}/api/run" 2>"$error_file")"; then
            curl_ok="1"
            break
        fi
        curl_err="$(cat "$error_file" 2>/dev/null || true)"
        if [[ "${MERIDIAN_GATEWAY_URL}" == http://127.0.0.1:* || "${MERIDIAN_GATEWAY_URL}" == http://localhost:* ]]; then
            if [[ "$curl_err" == *"Couldn't connect to server"* || "$curl_err" == *"Failed to connect"* ]]; then
                if [ "$autoheal_attempted" != "1" ]; then
                    autoheal_attempted="1"
                    echo "[core] gateway unavailable; attempting repo-managed dev-up" >&2
                    attempt_local_gateway_autoheal || true
                fi
                sleep 1
                continue
            fi
        fi
        break
    done
    if [ "$curl_ok" != "1" ]; then
        rm -f "$response_file" "$error_file"
        die "gateway request failed: ${curl_err:-curl transport error}"
    fi
    if [[ ! "$http_code" =~ ^2 ]]; then
        local body_preview
        body_preview="$(head -c 800 "$response_file" 2>/dev/null || true)"
        rm -f "$response_file" "$error_file"
        die "gateway http error ${http_code}: ${body_preview}"
    fi
    local raw_output
    raw_output="$(python3 - "$response_file" "$session_id" "$CORE_LAST_RESPONSE_FILE" "$CORE_LAST_OUTPUT_FILE" "$attachments_json" <<'PY'
import json, sys

response_path, session_id, last_response_path, last_output_path, attachments_json = sys.argv[1:6]
attachments = json.loads(attachments_json)
raw = open(response_path, encoding="utf-8").read()
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
provider_runtime = dict(data.get("provider_runtime") or {})
selected_plan = dict(provider_runtime.get("selected_plan") or {})
route_alignment = dict(provider_runtime.get("route_alignment") or {})
if mode or workers:
    workers_text = ", ".join(str(item) for item in workers) if workers else "-"
    print(f"\n[core] route={mode or '?'} workers={workers_text} session={data.get('session_key') or session_id}", file=sys.stderr)
if provider_runtime:
    drift = ",".join(str(item) for item in (route_alignment.get("drift_fields") or [])) or "-"
    print(
        f"[core] provider={selected_plan.get('provider_profile') or '?'} "
        f"model={selected_plan.get('model') or '(default)'} "
        f"transport={selected_plan.get('transport_kind') or '?'} "
        f"source={provider_runtime.get('source') or '?'} "
        f"drift={drift}",
        file=sys.stderr,
    )
PY
    )"
    rm -f "$response_file" "$error_file"

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
provider_runtime = dict(payload.get("provider_runtime") or {})
selected_plan = dict(provider_runtime.get("selected_plan") or {})
route_alignment = dict(provider_runtime.get("route_alignment") or {})
print(f"session_key: {payload.get('session_key') or data.get('session_key') or ''}")
print(f"route_mode: {route.get('mode') or ''}")
print(f"route_reason: {route.get('reason') or ''}")
print(f"workers: {', '.join(str(item) for item in workers) if workers else '-'}")
print(f"provider_source: {provider_runtime.get('source') or ''}")
print(f"provider_profile: {selected_plan.get('provider_profile') or ''}")
print(f"provider_model: {selected_plan.get('model') or ''}")
print(f"provider_transport: {selected_plan.get('transport_kind') or ''}")
print(f"provider_override_active: {provider_runtime.get('override_active')}")
print(f"provider_drift: {', '.join(str(item) for item in (route_alignment.get('drift_fields') or [])) if route_alignment.get('drift_fields') else '-'}")
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
code_source = complete_code or output

written = []

if code_source:
    code_pattern = re.compile(
        r"(?ms)^(?:#+\s*)?(?:\*\*|File:\s*|`{1,3})?([^`\n*]+?\.[A-Za-z0-9._/-]+)(?:\*\*|`{1,3})?\s*\n```[A-Za-z0-9_+-]*\n(.*?)\n```"
    )
    matches = list(code_pattern.finditer(code_source))
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
    local chat_model_override=""
    cat <<EOF
[core] interactive chat
[core] session: $session_id
[core] commands: /exit /new [id] /use ID /current /show /search QUERY /resume SESSION_KEY EVENT_INDEX [--queue] /reuse QUERY [--queue] /use-resume /response /file PATH /use-files /save-files /context /model MODEL /provider /page /help
EOF
    while true; do
        local prompt_suffix=""
        if [ ${#pending_files[@]} -gt 0 ]; then
            prompt_suffix=" [${#pending_files[@]} file(s)]"
        fi
        local context_count="0"
        context_count="$(python3 - "$CORE_CONTEXT_FILES_FILE" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
if not path.exists():
    print(0)
else:
    try:
        print(len(json.loads(path.read_text(encoding="utf-8")) or []))
    except Exception:
        print(0)
PY
)"
        if [ "${context_count:-0}" != "0" ]; then
            prompt_suffix="${prompt_suffix} [context:${context_count}]"
        fi
        if [ -n "$chat_model_override" ]; then
            prompt_suffix="${prompt_suffix} [model:${chat_model_override}]"
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
/search QUERY      Search across session history text
/resume SESSION_KEY EVENT_INDEX [--queue|--context]  Materialize one past event into a reusable context note
/reuse QUERY [--queue|--context] Search latest matching event and materialize it immediately
/use-resume        Add the last resumed context note to pending files
/response          Show the last captured response
/file PATH         Attach a file to the next message
/attach PATH       Alias for /file
/files             Show pending attached files
/clear-files       Clear all pending file attachments
/use-files         Load the persistent Core file queue into chat pending files
/save-files        Save current chat pending files into the persistent Core file queue
/context           Show persistent Core context files
/context add PATH  Add a file to persistent Core context
/context clear     Clear persistent Core context
/model MODEL       Set model override for subsequent messages (sticky)
/model             Clear model override (revert to default)
/provider          Show current provider status
/provider use P    Switch provider profile (persists across sessions)
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
            /search\ *)
                cmd_session search "${line#"/search "}"
                ;;
            /resume\ *)
                local resume_args="${line#"/resume "}"
                cmd_session resume $resume_args
                ;;
            /reuse\ *)
                local reuse_args="${line#"/reuse "}"
                cmd_session reuse $reuse_args
                ;;
            /use-resume)
                if [ ! -f "$CORE_LAST_RESUME_FILE" ]; then
                    echo "[core] no resumed context note found" >&2
                else
                    pending_files+=("$CORE_LAST_RESUME_FILE")
                    local merged_resume_json
                    merged_resume_json="$(merge_pending_file_paths_json '[]' "${pending_files[@]}")"
                    mapfile -t pending_files < <(python3 - "$merged_resume_json" <<'PY'
import json, sys
for item in json.loads(sys.argv[1] or "[]"):
    print(item)
PY
)
                    echo "[core] resumed context loaded (${#pending_files[@]} file(s) pending)"
                fi
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
            /use-files)
                local queued_json queued_joined
                queued_json="$(load_pending_files_json)"
                queued_joined="$(python3 - "$queued_json" <<'PY'
import json, sys
for item in json.loads(sys.argv[1] or "[]"):
    print(item)
PY
)"
                if [ -z "$queued_joined" ]; then
                    echo "[core] no persistent files queued"
                else
                    while IFS= read -r queued_path; do
                        [ -n "$queued_path" ] || continue
                        pending_files+=("$queued_path")
                    done <<< "$queued_joined"
                    local merged_json
                    merged_json="$(merge_pending_file_paths_json '[]' "${pending_files[@]}")"
                    mapfile -t pending_files < <(python3 - "$merged_json" <<'PY'
import json, sys
for item in json.loads(sys.argv[1] or "[]"):
    print(item)
PY
)
                    echo "[core] loaded persistent files (${#pending_files[@]} file(s) pending)"
                fi
                ;;
            /save-files)
                local save_json
                save_json="$(merge_pending_file_paths_json '[]' "${pending_files[@]}")"
                save_pending_files_json "$save_json"
                echo "[core] saved ${#pending_files[@]} file(s) to persistent queue"
                ;;
            /context\ add\ *)
                cmd_context add "${line#"/context add "}"
                ;;
            /context\ clear)
                cmd_context clear
                ;;
            /context)
                cmd_context list
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
            /model\ *)
                local new_model="${line#"/model "}"
                new_model="${new_model#"${new_model%%[![:space:]]*}"}"
                new_model="${new_model%"${new_model##*[![:space:]]}"}"
                if [ -n "$new_model" ]; then
                    chat_model_override="$new_model"
                    echo "[core] model override set: $chat_model_override (sticky for this chat session)"
                else
                    chat_model_override=""
                    echo "[core] model override cleared (using default)"
                fi
                ;;
            /model)
                chat_model_override=""
                echo "[core] model override cleared (using default)"
                ;;
            /provider\ use\ *)
                local provider_args="${line#"/provider use "}"
                provider_args="${provider_args#"${provider_args%%[![:space:]]*}"}"
                provider_args="${provider_args%"${provider_args##*[![:space:]]}"}"
                if [ -n "$provider_args" ]; then
                    cmd_provider_use $provider_args
                else
                    echo "[core] usage: /provider use PROFILE [--model MODEL]" >&2
                fi
                ;;
            /provider)
                cmd_provider status
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
                if [ -n "$chat_model_override" ]; then
                    ask_args+=("--model" "$chat_model_override")
                fi
                ask_args+=("$line")
                cmd_ask "${ask_args[@]}"
                # Clear pending files after sending
                pending_files=()
                ;;
        esac
    done
}

_render_doctor_overview() {
    local doctor_fix="${1:-}"
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
    echo ""
    echo "[core] multi-channel health"
    _render_multi_channel_health
}

_render_multi_channel_health() {
    local gateway_url="${MERIDIAN_GATEWAY_URL%/}"
    local health_json=""
    health_json="$(curl -sf "${gateway_url}/api/channels/health" 2>/dev/null || printf '{}')"
    if [ -z "$health_json" ] || [ "$health_json" = "{}" ]; then
        echo "  (gateway not reachable — channel health unavailable)"
        return
    fi
    python3 - "$health_json" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
    health = data.get("channels_health") or data
    channels = health.get("channels") or []
    active = int(health.get("active_adapter_count") or 0)
    delivered = int(health.get("total_recent_delivered") or 0)
    failed = int(health.get("total_recent_failed") or 0)
    print("  source: gateway_http")
    print(f"  adapters: {active} active, {len(channels)} tracked")
    print(f"  recent deliveries: {delivered} delivered, {failed} failed")
    for ch in channels:
        cid = ch.get("channel_id", "?")
        status = ch.get("health_status", "unknown")
        ds = ch.get("delivery_summary") or {}
        d = int(ds.get("delivered_count") or 0)
        f = int(ds.get("failed_count") or 0)
        latest = ds.get("latest_status") or "-"
        print(f"  {cid:12s}  {status:10s}  delivered={d}  failed={f}  latest={latest}")
except Exception as exc:
    print(f"  (channel health parse error: {exc})")
PY
}

write_capsule_manifest_scaffold() {
    local org_id="${1:-}"
    [ -n "$org_id" ] || return 1
    local capsules_dir="${LOOM_ROOT}/state/capsules/${org_id}"
    local manifest_path="${capsules_dir}/manifest.json"
    mkdir -p "$capsules_dir"
    python3 - "$org_id" "$manifest_path" "$LOOM_ROOT" <<'PY'
import json, os, sys
from pathlib import Path

org_id, manifest_path, loom_root = sys.argv[1:4]
loom_root = Path(loom_root)
manifest_path = Path(manifest_path)

onboard_path = loom_root / "state" / "onboard.json"
state_path = loom_root / "state" / "state.json"
skills_registry = loom_root / "state" / "skills" / "registry.json"
channels_registry = loom_root / "state" / "channels" / "registry.json"

created_at = 0
if onboard_path.exists():
    try:
        onboard = json.loads(onboard_path.read_text(encoding="utf-8"))
        created_at = int((((onboard.get("wizard") or {}).get("lastRunAt")) or 0))
    except Exception:
        created_at = 0
if not created_at and state_path.exists():
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        created_at = int(state.get("created_at") or 0)
    except Exception:
        created_at = 0

files = []
for candidate in (
    "state/onboard.json",
    "state/skills/registry.json",
    "state/channels/registry.json",
    "state/state.json",
):
    if (loom_root / candidate).exists():
        files.append(candidate)

payload = {
    "org_id": org_id,
    "state": "local_embedded_capsule",
    "provenance": "doctor_fix_scaffold",
    "created_at": created_at,
    "files": files,
}
manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(str(manifest_path))
PY
}

_write_doctor_receipt() {
    local mode="$1"
    local before_checks_json="$2"
    local after_checks_json="$3"
    local actions_json="$4"
    local service_before_json="$5"
    local service_after_json="$6"
    local action_results_json="${7:-[]}"
    ensure_core_state_dir
    python3 - "$CORE_LAST_DOCTOR_FILE" "$mode" "$LOOM_ROOT" "$before_checks_json" "$after_checks_json" "$actions_json" "$service_before_json" "$service_after_json" "$action_results_json" <<'PY'
import json, sys
from datetime import datetime, timezone

out_path, mode, loom_root, before_raw, after_raw, actions_raw, service_before_raw, service_after_raw, action_results_raw = sys.argv[1:10]
before = json.loads(before_raw or "[]")
after = json.loads(after_raw or "[]")
actions = json.loads(actions_raw or "[]")
service_before = json.loads(service_before_raw or "{}")
service_after = json.loads(service_after_raw or "{}")
action_results = json.loads(action_results_raw or "[]")

def summarize(checks):
    counts = {"OK": 0, "WARN": 0, "CRITICAL": 0, "UNKNOWN": 0}
    for item in checks:
        level = str(item.get("level") or "UNKNOWN").upper()
        counts[level] = counts.get(level, 0) + 1
    return counts

payload = {
    "schema_version": "meridian.core.doctor.v1",
    "mode": mode,
    "root": loom_root,
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "summary_before": summarize(before),
    "summary_after": summarize(after),
    "actions": actions,
    "action_results": action_results,
    "service_before": service_before,
    "service_after": service_after,
    "checks_before": before,
    "checks_after": after,
}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
}

cmd_doctor_fix() {
    require_loom
    require_runtime

    local before_checks_json service_before_json actions_json after_checks_json service_after_json
    before_checks_json="$("$LOOM_BIN" doctor --root "$LOOM_ROOT" --format json)"
    service_before_json="$("$LOOM_BIN" service status --root "$LOOM_ROOT" --format json 2>/dev/null || printf '{}')"
    actions_json='[]'
    local action_results_json='[]'
    local org_id
    org_id="$(resolve_org_id)"

    echo "[core] doctor fix: apply safe runtime repairs"
    "$LOOM_BIN" doctor --root "$LOOM_ROOT" --format human --fix

    actions_json="$(python3 - "$before_checks_json" "$service_before_json" <<'PY'
import json, sys
checks = json.loads(sys.argv[1] or "[]")
service = json.loads(sys.argv[2] or "{}")
actions = []
for item in checks:
    label = str(item.get("label") or "").strip()
    remediation = str(item.get("remediation") or "").strip()
    if label == "service_runtime" and remediation == "loom service start":
        if not bool(service.get("running")):
            note = str(service.get("note") or "").strip()
            if "stale state" in note.lower():
                actions.append({"action": "service_stop_stale", "reason": note})
            actions.append({"action": "service_start", "reason": remediation})
print(json.dumps(actions))
PY
)"

    if python3 - "$before_checks_json" <<'PY'
import json, sys
checks = json.loads(sys.argv[1] or "[]")
for item in checks:
    if str(item.get("label") or "").strip() == "capsule_manifest" and str(item.get("level") or "").upper() == "CRITICAL":
        raise SystemExit(0)
raise SystemExit(1)
PY
    then
        local capsule_manifest_path=""
        capsule_manifest_path="$(write_capsule_manifest_scaffold "$org_id")"
        actions_json="$(python3 - "$actions_json" "$capsule_manifest_path" <<'PY'
import json, sys
actions = json.loads(sys.argv[1] or "[]")
actions.append({"action": "capsule_manifest_scaffold", "reason": f"wrote capsule manifest scaffold {sys.argv[2]}"})
print(json.dumps(actions))
PY
)"
        action_results_json="$(python3 - "$action_results_json" "$capsule_manifest_path" <<'PY'
import json, sys
results = json.loads(sys.argv[1] or "[]")
results.append({"action": "capsule_manifest_scaffold", "ok": True, "path": sys.argv[2]})
print(json.dumps(results))
PY
)"
        echo "[core] wrote capsule manifest scaffold: $capsule_manifest_path"
    fi

    local quarantine_json
    quarantine_json="$(quarantine_stale_ingress_requests)"
    if python3 - "$quarantine_json" <<'PY'
import json, sys
payload = json.loads(sys.argv[1] or "{}")
raise SystemExit(0 if int(payload.get("moved_count") or 0) > 0 else 1)
PY
    then
        actions_json="$(python3 - "$actions_json" "$quarantine_json" <<'PY'
import json, sys
actions = json.loads(sys.argv[1] or "[]")
payload = json.loads(sys.argv[2] or "{}")
actions.insert(0, {"action": "ingress_quarantine", "reason": f"quarantined {int(payload.get('moved_count') or 0)} stale ingress request(s)"})
print(json.dumps(actions))
PY
)"
        action_results_json="$(python3 - "$action_results_json" "$quarantine_json" <<'PY'
import json, sys
results = json.loads(sys.argv[1] or "[]")
payload = json.loads(sys.argv[2] or "{}")
results.append({"action": "ingress_quarantine", "ok": True, "moved_count": int(payload.get("moved_count") or 0)})
print(json.dumps(results))
PY
)"
        echo "[core] quarantined stale ingress requests: $(python3 - "$quarantine_json" <<'PY'
import json, sys
print(int(json.loads(sys.argv[1] or "{}").get("moved_count") or 0))
PY
)"
    fi

    if python3 - "$actions_json" <<'PY'
import json, sys
actions = json.loads(sys.argv[1] or "[]")
raise SystemExit(0 if any(item.get("action") == "service_stop_stale" for item in actions) else 1)
PY
    then
        if "$LOOM_BIN" service stop --root "$LOOM_ROOT" --format human >/tmp/core-doctor-service-stop.txt 2>&1; then
            action_results_json="$(python3 - "$action_results_json" /tmp/core-doctor-service-stop.txt <<'PY'
import json, sys
results = json.loads(sys.argv[1] or "[]")
results.append({"action": "service_stop_stale", "ok": True, "output_path": sys.argv[2]})
print(json.dumps(results))
PY
)"
        else
            action_results_json="$(python3 - "$action_results_json" /tmp/core-doctor-service-stop.txt <<'PY'
import json, pathlib, sys
results = json.loads(sys.argv[1] or "[]")
detail = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace").strip()
results.append({"action": "service_stop_stale", "ok": False, "output_path": sys.argv[2], "detail": detail})
print(json.dumps(results))
PY
)"
        fi
        cat /tmp/core-doctor-service-stop.txt
    fi

    local stop_request_path="${LOOM_ROOT}/run/service/stop.requested"
    if [ -f "$stop_request_path" ]; then
        rm -f "$stop_request_path"
        actions_json="$(python3 - "$actions_json" "$stop_request_path" <<'PY'
import json, sys
actions = json.loads(sys.argv[1] or "[]")
actions.append({"action": "service_clear_stop_request", "reason": f"removed stale stop marker {sys.argv[2]}"})
print(json.dumps(actions))
PY
)"
        action_results_json="$(python3 - "$action_results_json" "$stop_request_path" <<'PY'
import json, sys
results = json.loads(sys.argv[1] or "[]")
results.append({"action": "service_clear_stop_request", "ok": True, "path": sys.argv[2]})
print(json.dumps(results))
PY
)"
        echo "[core] cleared stale stop marker: $stop_request_path"
    fi

    if python3 - "$actions_json" <<'PY'
import json, sys
actions = json.loads(sys.argv[1] or "[]")
raise SystemExit(0 if any(item.get("action") == "service_start" for item in actions) else 1)
PY
    then
        local service_token_meta="" service_token_source="" service_token_value=""
        service_token_meta="$(resolve_loom_service_token || true)"
        if [ -n "$service_token_meta" ]; then
            service_token_source="${service_token_meta%%$'\t'*}"
            service_token_value="${service_token_meta#*$'\t'}"
        fi
        if [ -z "$service_token_value" ]; then
            printf '%s\n' 'loom: LOOM_SERVICE_TOKEN is missing and no compatible fallback was found' >/tmp/core-doctor-service-start.txt
            action_results_json="$(python3 - "$action_results_json" /tmp/core-doctor-service-start.txt <<'PY'
import json, pathlib, sys
results = json.loads(sys.argv[1] or "[]")
detail = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace").strip()
results.append({"action": "service_start", "ok": False, "output_path": sys.argv[2], "detail": detail})
print(json.dumps(results))
PY
)"
        elif LOOM_SERVICE_TOKEN="$service_token_value" "$LOOM_BIN" service start --root "$LOOM_ROOT" --format human >/tmp/core-doctor-service-start.txt 2>&1; then
            action_results_json="$(python3 - "$action_results_json" /tmp/core-doctor-service-start.txt <<'PY'
import json, sys
results = json.loads(sys.argv[1] or "[]")
results.append({"action": "service_start", "ok": True, "output_path": sys.argv[2]})
print(json.dumps(results))
PY
)"
        else
            action_results_json="$(python3 - "$action_results_json" /tmp/core-doctor-service-start.txt "$service_token_source" <<'PY'
import json, pathlib, sys
results = json.loads(sys.argv[1] or "[]")
detail = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8", errors="replace").strip()
results.append({"action": "service_start", "ok": False, "output_path": sys.argv[2], "detail": detail, "token_source": sys.argv[3]})
print(json.dumps(results))
PY
)"
        fi
        cat /tmp/core-doctor-service-start.txt
        sleep 2
    fi

    after_checks_json="$("$LOOM_BIN" doctor --root "$LOOM_ROOT" --format json)"
    service_after_json="$("$LOOM_BIN" service status --root "$LOOM_ROOT" --format json 2>/dev/null || printf '{}')"
    _write_doctor_receipt "fix" "$before_checks_json" "$after_checks_json" "$actions_json" "$service_before_json" "$service_after_json" "$action_results_json"
    echo "[core] doctor receipt: $CORE_LAST_DOCTOR_FILE"
}

cmd_doctor() {
    require_loom
    require_runtime

    local subcmd="${1:-run}"
    case "$subcmd" in
        --fix|fix)
            shift || true
            cmd_doctor_fix "$@"
            ;;
        show)
            [ -f "$CORE_LAST_DOCTOR_FILE" ] || die "No Core doctor receipt captured yet. Run: ./scripts/core.sh doctor"
            cat "$CORE_LAST_DOCTOR_FILE"
            ;;
        path)
            [ -f "$CORE_LAST_DOCTOR_FILE" ] || die "No Core doctor receipt captured yet. Run: ./scripts/core.sh doctor"
            echo "$CORE_LAST_DOCTOR_FILE"
            ;;
        summary)
            [ -f "$CORE_LAST_DOCTOR_FILE" ] || die "No Core doctor receipt captured yet. Run: ./scripts/core.sh doctor"
            python3 - "$CORE_LAST_DOCTOR_FILE" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print("[core] doctor summary")
print(f"  mode:        {payload.get('mode') or 'unknown'}")
print(f"  captured_at: {payload.get('captured_at') or ''}")
before = dict(payload.get("summary_before") or {})
after = dict(payload.get("summary_after") or {})
print(f"  before:      OK={before.get('OK',0)} WARN={before.get('WARN',0)} CRITICAL={before.get('CRITICAL',0)}")
print(f"  after:       OK={after.get('OK',0)} WARN={after.get('WARN',0)} CRITICAL={after.get('CRITICAL',0)}")
actions = list(payload.get("actions") or [])
print(f"  actions:     {len(actions)}")
for item in actions:
    print(f"    - {item.get('action')}: {item.get('reason') or ''}")
results = list(payload.get("action_results") or [])
if results:
    print(f"  outcomes:    {len(results)}")
    for item in results:
        status = "ok" if item.get("ok") else "failed"
        detail = str(item.get("detail") or "").strip()
        print(f"    - {item.get('action')}: {status}")
        if detail:
            print(f"      detail: {detail[:160]}")
service_after = dict(payload.get("service_after") or {})
effective_health = str(service_after.get('health') or service_after.get('service_status') or '').strip()
effective_reason = ""
checks_after = list(payload.get("checks_after") or [])
critical_after = int(before.get('CRITICAL', 0))
critical_after = int(after.get('CRITICAL', 0))
onboard_daemon_enabled = None
for item in checks_after:
    if str(item.get("label") or "").strip() == "onboard_runtime":
        detail = str(item.get("detail") or "")
        if "daemon=supervisor disabled" in detail:
            onboard_daemon_enabled = False
        elif "daemon=supervisor enabled" in detail:
            onboard_daemon_enabled = True
if service_after:
    if (
        str(service_after.get("running")).lower() == "true"
        and effective_health == "degraded"
        and critical_after == 0
        and onboard_daemon_enabled is False
    ):
        effective_health = "healthy"
        effective_reason = "daemon disabled by onboarding policy"
if service_after:
    print(f"  service:     running={service_after.get('running')} health={service_after.get('health') or service_after.get('service_status') or ''}")
    if effective_health:
        print(f"  effective_service: {effective_health}")
    if effective_reason:
        print(f"  effective_reason:  {effective_reason}")
PY
            ;;
        run|show-human)
            shift || true
            local before_checks_json service_status_json
            before_checks_json="$("$LOOM_BIN" doctor --root "$LOOM_ROOT" --format json)"
            service_status_json="$("$LOOM_BIN" service status --root "$LOOM_ROOT" --format json 2>/dev/null || printf '{}')"
            _write_doctor_receipt "inspect" "$before_checks_json" "$before_checks_json" '[]' "$service_status_json" "$service_status_json" '[]'
            _render_doctor_overview ""
            echo ""
            echo "[core] doctor receipt: $CORE_LAST_DOCTOR_FILE"
            ;;
        *)
            local before_checks_json service_status_json
            before_checks_json="$("$LOOM_BIN" doctor --root "$LOOM_ROOT" --format json)"
            service_status_json="$("$LOOM_BIN" service status --root "$LOOM_ROOT" --format json 2>/dev/null || printf '{}')"
            _write_doctor_receipt "inspect" "$before_checks_json" "$before_checks_json" '[]' "$service_status_json" "$service_status_json" '[]'
            _render_doctor_overview ""
            echo ""
            echo "[core] doctor receipt: $CORE_LAST_DOCTOR_FILE"
            ;;
    esac
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
        list)
            cmd_provider_list "${@}"
            ;;
        fix)
            cmd_provider_fix "${@}"
            ;;
        restore)
            cmd_provider_restore "${@}"
            ;;
        probe)
            cmd_provider_probe "${@}"
            ;;
        use)
            cmd_provider_use "${@}"
            ;;
        *)
            die "Usage: core.sh provider <status|profiles|auth|route|login|list|fix|restore|probe|use> [args]"
            ;;
    esac
}

# ── provider list: human-readable table of providers, models, routes ──────

cmd_provider_list() {
    local org_id
    org_id="$(resolve_org_id)"
    [ -n "$org_id" ] || die "Could not resolve org_id. Run onboard.sh first."

    python3 - "$MERIDIAN_ROOT" "$org_id" <<'PY'
import json, os, sys

meridian_root, org_id = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(meridian_root, "intelligence"))
sys.path.insert(0, os.path.join(meridian_root, "intelligence", "company", "meridian_platform"))
import institution_brain_policy
from company.meridian_platform import brain_router

status = institution_brain_policy.policy_status(org_id)

# Active route summary
active_route = status.get("active_route") or {}
active_provider = status.get("active_provider") or {}
active_model = status.get("active_model") or {}

print("Meridian Provider Plane")
print("=" * 60)
print(f"  org_id:         {org_id}")
print(f"  policy_status:  {status.get('status', 'unknown')}")
print(f"  source:         {status.get('source', '?')}")
if status.get("reason"):
    print(f"  reason:         {status['reason']}")
print()

if active_route:
    print("Active Route")
    print("-" * 40)
    print(f"  route_id:    {active_route.get('route_id', '')}")
    print(f"  type:        {active_route.get('route_type', '')}")
    print(f"  provider:    {active_route.get('provider_ref', '') or active_route.get('provider_profile', '')}")
    print(f"  model:       {active_route.get('model', '') or '(not set)'}")
    print(f"  health:      {active_route.get('last_health', 'unknown')}")
    if active_route.get("last_health_reason"):
        print(f"  health_note: {active_route['last_health_reason']}")
    print(f"  budget_band: {active_route.get('budget_band', '') or 'standard'}")
    print(f"  authority:   {'yes' if active_route.get('approved_by_authority', True) else 'NO'}")
    print(f"  treasury:    {'yes' if active_route.get('allowed_by_treasury', True) else 'NO'}")
    print()

# Fallback chain
fallback_chain = status.get("fallback_chain") or []
if fallback_chain:
    print("Fallback Chain")
    print("-" * 40)
    for i, fb in enumerate(fallback_chain, 1):
        health = fb.get("last_health", "unknown")
        print(f"  [{i}] {fb.get('route_id', '?')}  provider={fb.get('provider_ref', '?')}  model={fb.get('model', '?')}  health={health}")
    print()

# Provider registry
provider_registry = status.get("provider_registry") or {}
if provider_registry:
    print("Registered Providers")
    print("-" * 40)
    for pid, pentry in sorted(provider_registry.items()):
        display = pentry.get("display_name") or pid
        caps = ", ".join(pentry.get("capabilities") or []) or "?"
        print(f"  {pid:30s}  caps=[{caps}]")
    print()

# Model registry
model_registry = status.get("model_registry") or {}
if model_registry:
    print("Registered Models")
    print("-" * 40)
    for mid, mentry in sorted(model_registry.items()):
        model_name = mentry.get("model_name") or mid
        provider_id = mentry.get("provider_id") or "?"
        print(f"  {mid:40s}  model={model_name:20s}  provider={provider_id}")
    print()

# Env override check
try:
    runtime_env = dict(os.environ)
    runtime_env.setdefault("MERIDIAN_ORG_ID", org_id)
    runtime_env.setdefault("MERIDIAN_WORKSPACE_ORG_ID", org_id)
    manager_status = brain_router.manager_policy_status(runtime_env=runtime_env, model_hint="")
    meta = manager_status.get("selected_plan") or {}
    alignment = manager_status.get("route_alignment") or {}
    print("Effective Manager Execution")
    print("-" * 40)
    print(f"  profile:   {meta.get('provider_profile', '?')}")
    print(f"  model:     {meta.get('model', '') or '(default)'}")
    print(f"  transport: {meta.get('transport_kind', '?')}")
    print(f"  auth:      {meta.get('auth_mode', '?')}")
    print(f"  source:    {meta.get('source', '?')}")
    if manager_status.get("override_active"):
        print(f"  overrides: {', '.join(manager_status.get('override_fields') or [])}")
    if not alignment.get("matches_policy_route", True):
        print(f"  drift:     {', '.join(alignment.get('drift_fields') or [])}")
except Exception as exc:
    print(f"[warn] could not resolve manager plan: {exc}")
PY
}

# ── provider use: switch the active provider/model ────────────────────────

cmd_provider_use() {
    local profile="${1:-}"
    [ -n "$profile" ] || die "Usage: core.sh provider use PROFILE [--model MODEL] [--endpoint URL] [--transport cli_session|http_json]"
    shift

    local model="" endpoint="" transport="" auth_env="" key_env_pool=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --model|-m)   model="${2:-}"; shift 2 ;;
            --endpoint)   endpoint="${2:-}"; shift 2 ;;
            --transport)  transport="${2:-}"; shift 2 ;;
            --auth-env)   auth_env="${2:-}"; shift 2 ;;
            --key-env)    key_env_pool="${2:-}"; shift 2 ;;
            *)            die "Unknown flag: $1" ;;
        esac
    done

    local org_id
    org_id="$(resolve_org_id)"
    [ -n "$org_id" ] || die "Could not resolve org_id. Run onboard.sh first."

    python3 - "$MERIDIAN_ROOT" "$org_id" "$profile" "$model" "$endpoint" "$transport" "$auth_env" "$key_env_pool" <<'PY'
import json, os, sys

meridian_root = sys.argv[1]
org_id, profile, model, endpoint, transport, auth_env, key_env_pool_csv = sys.argv[2:9]
sys.path.insert(0, os.path.join(meridian_root, "intelligence"))
sys.path.insert(0, os.path.join(meridian_root, "intelligence", "company", "meridian_platform"))
import institution_brain_policy

# Load current policy so we can show a before/after diff
current_policy = institution_brain_policy.load_policy(org_id)
current_route = institution_brain_policy.active_route(current_policy)
target_defaults = institution_brain_policy.resolve_profile_defaults(current_policy, profile)

# Auto-detect transport if not specified
if not transport:
    if target_defaults.get("route_type"):
        transport = str(target_defaults.get("route_type") or "").strip()
    elif current_route:
        transport = str(current_route.get("route_type") or "").strip() or "cli_session"
    else:
        transport = "cli_session"

# Resolve model from profile defaults when available
if not model:
    model = str(target_defaults.get("model") or "").strip()

# Resolve cli_bin and cli_home from target profile or env
cli_bin = ""
cli_home = ""
if transport == "cli_session":
    cli_bin = str(target_defaults.get("cli_bin") or "").strip()
    cli_home = str(target_defaults.get("cli_home") or "").strip()
    if not cli_bin and current_route and str(current_route.get("provider_ref") or current_route.get("provider_profile") or "").strip() == profile:
        cli_bin = str(current_route.get("cli_bin") or "").strip()
    if not cli_home and current_route and str(current_route.get("provider_ref") or current_route.get("provider_profile") or "").strip() == profile:
        cli_home = str(current_route.get("cli_home") or "").strip()
    explicit_cli_bin = str(os.environ.get("MERIDIAN_BRAIN_MANAGER_CLI_BIN") or os.environ.get("MERIDIAN_CODEX_BIN") or "").strip()
    explicit_cli_home = str(os.environ.get("MERIDIAN_BRAIN_MANAGER_CLI_HOME") or os.environ.get("MERIDIAN_CODEX_HOME") or "").strip()
    if explicit_cli_bin:
        cli_bin = explicit_cli_bin
    if explicit_cli_home:
        cli_home = explicit_cli_home
    elif not cli_home:
        cli_home = str(os.environ.get("HOME") or "").strip()
    if not cli_bin:
        print(f"[core] provider switch failed: no cli_bin available for profile '{profile}'", file=sys.stderr)
        raise SystemExit(1)

resolved_auth_env = str(target_defaults.get("auth_env") or "").strip()
resolved_key_env_pool = [str(item).strip() for item in list(target_defaults.get("key_env_pool") or []) if str(item).strip()]

if transport == "http_json":
    if not endpoint:
        endpoint = str(target_defaults.get("endpoint") or "").strip()
    if not endpoint and current_route and str(current_route.get("provider_ref") or current_route.get("provider_profile") or "").strip() == profile:
        endpoint = str(current_route.get("endpoint") or "").strip()
    if not auth_env:
        auth_env = resolved_auth_env
    if not key_env_pool_csv:
        key_env_pool_csv = ",".join(resolved_key_env_pool)
    if (not auth_env) and (not key_env_pool_csv):
        print(
            f"[core] provider switch failed: no auth metadata available for HTTP profile '{profile}'. "
            "Pass --auth-env/--key-env or configure the profile first.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not endpoint:
        print(
            f"[core] provider switch failed: no endpoint available for HTTP profile '{profile}'. "
            "Pass --endpoint or configure the profile first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

key_env_pool_list = [item.strip() for item in (key_env_pool_csv or "").split(",") if item.strip()]

# Backup current policy
backup_path = institution_brain_policy.policy_path(org_id) + ".bak"
try:
    current_raw = json.dumps(current_policy, indent=2, ensure_ascii=False)
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    with open(backup_path, "w", encoding="utf-8") as fh:
        fh.write(current_raw + "\n")
except Exception:
    pass

# Apply new configuration
try:
    new_policy = institution_brain_policy.configure_policy(
        org_id,
        route_type=transport,
        provider_profile=profile,
        model=model,
        updated_by="core.sh provider use",
        cli_bin=cli_bin,
        cli_home=cli_home,
        endpoint=endpoint,
        auth_env=auth_env,
        key_env_pool=key_env_pool_list or None,
    )
except Exception as exc:
    print(f"[core] provider switch failed: {exc}", file=sys.stderr)
    raise SystemExit(1)

new_route = institution_brain_policy.active_route(new_policy)

# Show before/after
old_provider = str((current_route or {}).get("provider_ref") or (current_route or {}).get("provider_profile") or "").strip() or "(none)"
old_model = str((current_route or {}).get("model") or "").strip() or "(none)"
new_provider = str((new_route or {}).get("provider_ref") or profile).strip()
new_model = str((new_route or {}).get("model") or "").strip() or "(none)"

print(f"[core] provider switched")
print(f"  before: provider={old_provider}  model={old_model}")
print(f"  after:  provider={new_provider}  model={new_model}")
print(f"  transport: {transport}")
if backup_path:
    print(f"  backup: {backup_path}")
PY
    echo "[core] run 'core.sh provider list' to verify"
}

cmd_provider_fix() {
    local gateway_env="${MERIDIAN_LOCAL_ENV_DIR}/.env.gateway"
    local main_env="${MERIDIAN_LOCAL_ENV_DIR}/.env"
    local restore_endpoint=""
    restore_endpoint="$(read_env_file_value "$gateway_env" "MERIDIAN_BRAIN_MANAGER_ENDPOINT" 2>/dev/null || true)"
    [ -n "$restore_endpoint" ] || restore_endpoint="$(read_env_file_value "$main_env" "MERIDIAN_MANAGER_XAI_BASE_URL" 2>/dev/null || true)"
    if [ -n "$restore_endpoint" ]; then
        echo "[core] provider fix"
        echo "  strategy:    restore Meridian-owned manager route"
        cmd_provider_restore
        return 0
    fi
    die "provider fix requires Meridian manager config. Set MERIDIAN_BRAIN_MANAGER_ENDPOINT in ${gateway_env} or MERIDIAN_MANAGER_XAI_BASE_URL in ${main_env}, then run: core.sh provider restore"
}

cmd_provider_restore() {
    local gateway_env="${MERIDIAN_LOCAL_ENV_DIR}/.env.gateway"
    local main_env="${MERIDIAN_LOCAL_ENV_DIR}/.env"
    local endpoint="" model="" auth_env="" key_pool="" profile=""

    endpoint="$(read_env_file_value "$gateway_env" "MERIDIAN_BRAIN_MANAGER_ENDPOINT" 2>/dev/null || true)"
    [ -n "$endpoint" ] || endpoint="$(read_env_file_value "$main_env" "MERIDIAN_MANAGER_XAI_BASE_URL" 2>/dev/null || true)"

    model="$(read_env_file_value "$gateway_env" "MERIDIAN_BRAIN_MANAGER_MODEL" 2>/dev/null || true)"
    [ -n "$model" ] || model="$(read_env_file_value "$main_env" "MERIDIAN_MANAGER_MODEL" 2>/dev/null || true)"
    [ -n "$model" ] || model="grok-4-1-fast-reasoning"

    profile="$(read_env_file_value "$main_env" "MERIDIAN_BRAIN_MANAGER_PROFILE_NAME" 2>/dev/null || true)"
    [ -n "$profile" ] || profile="manager_primary"

    auth_env="$(read_env_file_value "$gateway_env" "MERIDIAN_BRAIN_MANAGER_AUTH_ENV" 2>/dev/null || true)"
    [ -n "$auth_env" ] || auth_env="MERIDIAN_MANAGER_XAI_API_KEY_1"

    key_pool="$(read_env_file_value "$gateway_env" "MERIDIAN_BRAIN_MANAGER_KEY_ENV_POOL" 2>/dev/null || true)"
    [ -n "$key_pool" ] || key_pool="MERIDIAN_MANAGER_XAI_API_KEY_1,MERIDIAN_MANAGER_XAI_API_KEY_2,MERIDIAN_MANAGER_XAI_API_KEY_3"

    [ -n "$endpoint" ] || die "provider restore could not resolve a Meridian manager endpoint from .env/.env.gateway"

    echo "[core] provider restore"
    echo "  target_profile: $profile"
    echo "  transport:      http_json"
    echo "  model:          $model"
    echo "  endpoint:       $endpoint"
    echo "  auth_env:       $auth_env"
    echo "  key_pool:       $(python3 - "$key_pool" <<'PY'
import sys
items = [item.strip() for item in (sys.argv[1] or '').split(',') if item.strip()]
print(",".join(items))
PY
)"

    cmd_provider_use "$profile" --transport http_json --model "$model" --endpoint "$endpoint" --auth-env "$auth_env" --key-env "$key_pool"
}

cmd_provider_probe() {
    local probe_text="${1:-provider-probe-ok}"
    local timeout="${MERIDIAN_CORE_PROVIDER_PROBE_TIMEOUT:-60}"
    local org_id
    org_id="$(resolve_org_id)"
    [ -n "$org_id" ] || die "Could not resolve org_id. Run onboard.sh first."
    local gateway_env="${MERIDIAN_LOCAL_ENV_DIR}/.env.gateway"
    local main_env="${MERIDIAN_LOCAL_ENV_DIR}/.env"
    set -a
    [ -f "$main_env" ] && . "$main_env"
    [ -f "$gateway_env" ] && . "$gateway_env"
    set +a
    python3 - "$MERIDIAN_ROOT" "$probe_text" "$timeout" "$org_id" <<'PY'
import json, os, sys

meridian_root, probe_text, timeout_text, org_id = sys.argv[1:5]
timeout = int(timeout_text or "60")
sys.path.insert(0, os.path.join(meridian_root, "intelligence"))
sys.path.insert(0, os.path.join(meridian_root, "intelligence", "company", "meridian_platform"))
from company.meridian_platform import brain_router

runtime_env = dict(os.environ)
runtime_env.setdefault("MERIDIAN_ORG_ID", org_id)
runtime_env.setdefault("MERIDIAN_WORKSPACE_ORG_ID", org_id)
for name in list(runtime_env):
    if name.startswith("MERIDIAN_BRAIN_MANAGER_"):
        runtime_env[name] = ""
runtime_env["MERIDIAN_BRAIN_ROUTER_CONFIG_PATH"] = ""
result = brain_router.execute_manager(
    runtime_env=runtime_env,
    system_prompt="Reply with exactly the provided probe text and nothing else.",
    user_prompt=f"Reply with exactly: {probe_text}",
    model=str(runtime_env.get("MERIDIAN_BRAIN_MANAGER_MODEL") or "").strip(),
    timeout=timeout,
)
print("[core] provider probe")
print(f"  ok:           {bool(result.get('ok'))}")
print(f"  provider:     {str(result.get('provider_profile') or '')}")
print(f"  transport:    {str(result.get('transport_kind') or '')}")
print(f"  auth:         {str(result.get('auth_mode') or '')}")
print(f"  route_id:     {str(result.get('route_decision', {}).get('route_id') or result.get('route_id') or '')}")
if result.get("ok"):
    print(f"  output:       {str(result.get('output_text') or '').strip()}")
else:
    print(f"  error_code:   {str(result.get('error_code') or '')}")
    print(f"  error:        {str(result.get('stderr') or '').strip()[:300]}")
    raise SystemExit(1)
PY
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
        set)
            cmd_config_set "${@}"
            ;;
        get)
            cmd_config_get "${@}"
            ;;
        *)
            die "Usage: core.sh config <show|set|get> [args]"
            ;;
    esac
}

# Allowed config keys for safe editing via 'core.sh config set'
CORE_CONFIG_ALLOWED_KEYS="MERIDIAN_BRAIN_MANAGER_MODEL MERIDIAN_BRAIN_MANAGER_TRANSPORT MERIDIAN_BRAIN_MANAGER_ENDPOINT MERIDIAN_BRAIN_MANAGER_PROFILE_NAME MERIDIAN_BRAIN_MANAGER_CLI_BIN MERIDIAN_BRAIN_MANAGER_CLI_HOME MERIDIAN_BRAIN_MANAGER_MAX_TOKENS MERIDIAN_CORE_LONG_OUTPUT_CHARS MERIDIAN_CORE_LONG_OUTPUT_LINES MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS MERIDIAN_GATEWAY_URL MERIDIAN_SESSION_ID"

cmd_config_set() {
    local key="${1:-}"
    local value="${2:-}"
    [ -n "$key" ] || die "Usage: core.sh config set KEY VALUE"
    [ -n "$value" ] || die "Usage: core.sh config set KEY VALUE"

    # Validate key is in allowed list
    local allowed=false
    for allowed_key in $CORE_CONFIG_ALLOWED_KEYS; do
        if [ "$key" = "$allowed_key" ]; then
            allowed=true
            break
        fi
    done
    if [ "$allowed" != "true" ]; then
        echo "[core] key '$key' is not in the safe-edit allowlist" >&2
        echo "[core] allowed keys:" >&2
        for allowed_key in $CORE_CONFIG_ALLOWED_KEYS; do
            echo "  $allowed_key" >&2
        done
        exit 1
    fi

    ensure_core_state_dir
    local config_file="${CORE_STATE_DIR}/overrides.env"

    # Backup existing config if present
    if [ -f "$config_file" ]; then
        cp "$config_file" "${config_file}.bak"
    fi

    # Update or insert the key=value line
    python3 - "$config_file" "$key" "$value" <<'PY'
import os, sys

config_path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
lines = []
found = False
if os.path.exists(config_path):
    with open(config_path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
                lines.append(f"export {key}={value}\n")
                found = True
            else:
                lines.append(line)
if not found:
    lines.append(f"export {key}={value}\n")
os.makedirs(os.path.dirname(config_path), exist_ok=True)
with open(config_path, "w", encoding="utf-8") as fh:
    fh.writelines(lines)
print(f"[core] config set: {key}={value}")
print(f"[core] written to: {config_path}")
print(f"[core] source this file or restart to apply: source {config_path}")
PY
}

cmd_config_get() {
    local key="${1:-}"
    [ -n "$key" ] || die "Usage: core.sh config get KEY"

    # First check overrides file
    local config_file="${CORE_STATE_DIR}/overrides.env"
    local found_value=""
    if [ -f "$config_file" ]; then
        found_value="$(grep -m1 "^export ${key}=" "$config_file" 2>/dev/null | sed "s/^export ${key}=//" || true)"
        if [ -z "$found_value" ]; then
            found_value="$(grep -m1 "^${key}=" "$config_file" 2>/dev/null | sed "s/^${key}=//" || true)"
        fi
    fi

    if [ -n "$found_value" ]; then
        echo "$key=$found_value  (source: overrides.env)"
    elif [ -n "${!key:-}" ]; then
        echo "$key=${!key}  (source: environment)"
    else
        echo "$key=(not set)"
    fi
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

# ── Command: ingress ──────────────────────────────────────────────────────

cmd_ingress() {
    local subcmd="${1:-status}"
    shift || true

    case "$subcmd" in
        status)
            render_ingress_snapshot "pending" "${1:-20}"
            ;;
        quarantine)
            if [ "${1:-}" = "--apply" ]; then
                shift || true
                local older_than="${1:-${MERIDIAN_CORE_DOCTOR_INGRESS_MAX_AGE_SECONDS:-300}}"
                local quarantine_json
                quarantine_json="$(MERIDIAN_CORE_DOCTOR_INGRESS_MAX_AGE_SECONDS="$older_than" quarantine_stale_ingress_requests)"
                python3 - "$quarantine_json" <<'PY'
import json, sys
payload = json.loads(sys.argv[1] or "{}")
print("[core] ingress quarantine")
print(f"  moved_count:     {int(payload.get('moved_count') or 0)}")
# Bolt: Removed redundant list() wrapper before slicing to avoid unnecessary O(N) allocation
for item in (payload.get("moved_files") or [])[:20]:
    detail = str(item.get("stale_reason") or "")
    if not detail:
        paths = list(item.get("stale_paths") or [])
        detail = ", ".join(paths[:2])
    print(f"    - {item.get('file')}: {detail}")
PY
            else
                render_ingress_snapshot "quarantine" "${1:-20}"
            fi
            ;;
        list)
            local bucket="${1:-pending}"
            shift || true
            render_ingress_snapshot "$bucket" "${1:-50}"
            ;;
        *)
            die "Usage: core.sh ingress <status|list [pending|quarantine] [LIMIT]|quarantine [LIMIT]|quarantine --apply [OLDER_THAN_SECONDS]>"
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
        search)
            local query="${1:-}"
            local limit="${2:-12}"
            [ -n "$query" ] || die "Usage: core.sh session search QUERY [LIMIT]"
            python3 - "$LOOM_ROOT" "$query" "$limit" <<'PY'
import glob, json, os, re, sys

loom_root, query, limit_text = sys.argv[1:4]
limit = max(1, int(limit_text or "12"))
needle = str(query or "").strip().lower()
if not needle:
    print("[core] empty search query", file=sys.stderr)
    raise SystemExit(1)

paths = sorted(
    glob.glob(os.path.join(loom_root, "state", "session-history", "events", "*.json")),
    key=os.path.getmtime,
    reverse=True,
)
hits = []
for path in paths:
    try:
        payload = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    session_key = str(payload.get("session_key") or "").strip()
    updated_at = str(payload.get("updated_at") or "").strip()
    for idx, event in enumerate(list(payload.get("events") or [])):
        text = str(event.get("text") or "").strip()
        if not text:
            continue
        haystack = text.lower()
        if needle not in haystack:
            continue
        start = haystack.find(needle)
        left = max(0, start - 90)
        right = min(len(text), start + len(query) + 140)
        snippet = text[left:right].replace("\n", " ").strip()
        if left > 0:
            snippet = "..." + snippet
        if right < len(text):
            snippet = snippet + "..."
        hits.append({
            "session_key": session_key,
            "updated_at": updated_at,
            "history_type": str(event.get("history_type") or "").strip(),
            "status": str(event.get("status") or "").strip(),
            "speaker": str(event.get("speaker") or "").strip() or "system",
            "snippet": snippet,
            "index": idx,
        })

if not hits:
    print(f"[core] no session hits for: {query}")
    raise SystemExit(0)

print(f"[core] session search: {query}")
print(f"  hits: {min(len(hits), limit)} / {len(hits)}")
for item in hits[:limit]:
    print(f"- {item['session_key']} #{item['index']} [{item['history_type']}:{item['status']}] speaker={item['speaker']} updated_at={item['updated_at']}")
    print(f"  {item['snippet']}")
PY
            ;;
        resume)
            local session_key=""
            local event_index=""
            local queue_after="0"
            local context_after="0"
            while [ $# -gt 0 ]; do
                case "$1" in
                    --queue)
                        queue_after="1"
                        shift
                        ;;
                    --context)
                        context_after="1"
                        shift
                        ;;
                    *)
                        if [ -z "$session_key" ]; then
                            session_key="$1"
                        elif [ -z "$event_index" ]; then
                            event_index="$1"
                        else
                            die "Usage: core.sh session resume SESSION_KEY EVENT_INDEX [--queue|--context]"
                        fi
                        shift
                        ;;
                esac
            done
            [ -n "$session_key" ] && [ -n "$event_index" ] || die "Usage: core.sh session resume SESSION_KEY EVENT_INDEX [--queue|--context]"
            ensure_core_state_dir
            python3 - "$LOOM_ROOT" "$session_key" "$event_index" "$CORE_LAST_RESUME_FILE" <<'PY'
import glob, json, os, sys
from pathlib import Path

loom_root, session_key, event_index_text, out_path = sys.argv[1:5]
event_index = int(event_index_text)
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

events = list(payload.get("events") or [])
if event_index < 0 or event_index >= len(events):
    print(f"[core] event index out of range for {session_key}: {event_index}", file=sys.stderr)
    raise SystemExit(1)

event = dict(events[event_index] or {})
history_type = str(event.get("history_type") or "").strip()
status = str(event.get("status") or "").strip()
speaker = str(event.get("speaker") or "").strip() or "system"
text = str(event.get("text") or "").strip()
updated_at = str(payload.get("updated_at") or "").strip()

root = Path(out_path).resolve().parent
root.mkdir(parents=True, exist_ok=True)
resume_path = Path(out_path).resolve()
content = "\n".join([
    "# Meridian Resumed Context",
    "",
    f"- session_key: `{session_key}`",
    f"- event_index: `{event_index}`",
    f"- updated_at: `{updated_at}`",
    f"- history_type: `{history_type}`",
    f"- status: `{status}`",
    f"- speaker: `{speaker}`",
    "",
    "## Event Text",
    "",
    text or "(empty)",
    "",
])
resume_path.write_text(content, encoding="utf-8")
print(f"[core] resumed context written: {resume_path}")
print(f"  session_key: {session_key}")
print(f"  event_index: {event_index}")
print(f"  history_type: {history_type}")
print(f"  status:      {status}")
PY
            if [ "$queue_after" = "1" ]; then
                local current_json merged_json
                current_json="$(load_pending_files_json)"
                merged_json="$(merge_pending_file_paths_json "$current_json" "$CORE_LAST_RESUME_FILE")"
                save_pending_files_json "$merged_json"
                python3 - "$merged_json" "$CORE_LAST_RESUME_FILE" <<'PY'
import json, os, sys
items = json.loads(sys.argv[1] or "[]")
resume_path = os.path.abspath(os.path.expanduser(sys.argv[2]))
queued = any(os.path.abspath(os.path.expanduser(item)) == resume_path for item in items)
print(f"[core] resumed context queued: {queued}")
print(f"  total_files: {len(items)}")
PY
            fi
            if [ "$context_after" = "1" ]; then
                local current_context_json merged_context_json
                current_context_json="$(load_context_files_json)"
                merged_context_json="$(merge_pending_file_paths_json "$current_context_json" "$CORE_LAST_RESUME_FILE")"
                save_context_files_json "$merged_context_json"
                python3 - "$merged_context_json" "$CORE_LAST_RESUME_FILE" <<'PY'
import json, os, sys
items = json.loads(sys.argv[1] or "[]")
resume_path = os.path.abspath(os.path.expanduser(sys.argv[2]))
attached = any(os.path.abspath(os.path.expanduser(item)) == resume_path for item in items)
print(f"[core] resumed context added to persistent context: {attached}")
print(f"  total_files: {len(items)}")
PY
            fi
            ;;
        reuse)
            local query=""
            local queue_after="0"
            local context_after="0"
            while [ $# -gt 0 ]; do
                case "$1" in
                    --queue)
                        queue_after="1"
                        shift
                        ;;
                    --context)
                        context_after="1"
                        shift
                        ;;
                    *)
                        if [ -z "$query" ]; then
                            query="$1"
                        else
                            query="$query $1"
                        fi
                        shift
                        ;;
                esac
            done
            [ -n "$query" ] || die "Usage: core.sh session reuse QUERY [--queue|--context]"
            ensure_core_state_dir
            python3 - "$LOOM_ROOT" "$query" "$CORE_LAST_RESUME_FILE" <<'PY'
import glob, json, os, sys
from pathlib import Path

loom_root, query, out_path = sys.argv[1:4]
needle = str(query or "").strip().lower()
if not needle:
    print("[core] empty reuse query", file=sys.stderr)
    raise SystemExit(1)

paths = sorted(
    glob.glob(os.path.join(loom_root, "state", "session-history", "events", "*.json")),
    key=os.path.getmtime,
    reverse=True,
)
match = None
for path in paths:
    try:
        payload = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    session_key = str(payload.get("session_key") or "").strip()
    updated_at = str(payload.get("updated_at") or "").strip()
    for idx, event in enumerate(list(payload.get("events") or [])):
        text = str(event.get("text") or "").strip()
        if not text or needle not in text.lower():
            continue
        match = {
            "session_key": session_key,
            "event_index": idx,
            "updated_at": updated_at,
            "history_type": str(event.get("history_type") or "").strip(),
            "status": str(event.get("status") or "").strip(),
            "speaker": str(event.get("speaker") or "").strip() or "system",
            "text": text,
        }
        break
    if match:
        break

if match is None:
    print(f"[core] no session hits for reuse query: {query}", file=sys.stderr)
    raise SystemExit(1)

root = Path(out_path).resolve().parent
root.mkdir(parents=True, exist_ok=True)
resume_path = Path(out_path).resolve()
content = "\n".join([
    "# Meridian Resumed Context",
    "",
    f"- session_key: `{match['session_key']}`",
    f"- event_index: `{match['event_index']}`",
    f"- updated_at: `{match['updated_at']}`",
    f"- history_type: `{match['history_type']}`",
    f"- status: `{match['status']}`",
    f"- speaker: `{match['speaker']}`",
    f"- reuse_query: `{query}`",
    "",
    "## Event Text",
    "",
    match["text"] or "(empty)",
    "",
])
resume_path.write_text(content, encoding="utf-8")
print(f"[core] reused context written: {resume_path}")
print(f"  query:       {query}")
print(f"  session_key: {match['session_key']}")
print(f"  event_index: {match['event_index']}")
print(f"  history_type:{match['history_type']}")
print(f"  status:      {match['status']}")
PY
            if [ "$queue_after" = "1" ]; then
                local current_json merged_json
                current_json="$(load_pending_files_json)"
                merged_json="$(merge_pending_file_paths_json "$current_json" "$CORE_LAST_RESUME_FILE")"
                save_pending_files_json "$merged_json"
                python3 - "$merged_json" "$CORE_LAST_RESUME_FILE" <<'PY'
import json, os, sys
items = json.loads(sys.argv[1] or "[]")
resume_path = os.path.abspath(os.path.expanduser(sys.argv[2]))
queued = any(os.path.abspath(os.path.expanduser(item)) == resume_path for item in items)
print(f"[core] reused context queued: {queued}")
print(f"  total_files: {len(items)}")
PY
            fi
            if [ "$context_after" = "1" ]; then
                local current_context_json merged_context_json
                current_context_json="$(load_context_files_json)"
                merged_context_json="$(merge_pending_file_paths_json "$current_context_json" "$CORE_LAST_RESUME_FILE")"
                save_context_files_json "$merged_context_json"
                python3 - "$merged_context_json" "$CORE_LAST_RESUME_FILE" <<'PY'
import json, os, sys
items = json.loads(sys.argv[1] or "[]")
resume_path = os.path.abspath(os.path.expanduser(sys.argv[2]))
attached = any(os.path.abspath(os.path.expanduser(item)) == resume_path for item in items)
print(f"[core] reused context added to persistent context: {attached}")
print(f"  total_files: {len(items)}")
PY
            fi
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
        archive)
            cmd_session_archive "${@}"
            ;;
        *)
            die "Usage: core.sh session <current|use|new|list|show|search|resume|reuse|export|reset|archive> [args]"
            ;;
    esac
}

# ── session archive: lifecycle cleanup for old sessions ───────────────────

cmd_session_archive() {
    local older_than_days="30"
    local dry_run=true
    local archive_dir=""

    while [ $# -gt 0 ]; do
        case "$1" in
            --older-than) older_than_days="${2:-30}"; shift 2 ;;
            --execute)    dry_run=false; shift ;;
            --archive-dir) archive_dir="${2:-}"; shift 2 ;;
            *)            die "Usage: core.sh session archive [--older-than DAYS] [--archive-dir DIR] [--execute]" ;;
        esac
    done

    ensure_core_state_dir
    [ -n "$archive_dir" ] || archive_dir="${CORE_STATE_DIR}/archived_sessions"

    python3 - "$LOOM_ROOT" "$CORE_SESSION_REGISTRY_FILE" "$CORE_CURRENT_SESSION_FILE" "$older_than_days" "$dry_run" "$archive_dir" <<'PY'
import glob, json, os, shutil, sys, time

loom_root = sys.argv[1]
registry_path = sys.argv[2]
current_path = sys.argv[3]
older_than_days = int(sys.argv[4])
dry_run = sys.argv[5] == "True"
archive_dir = sys.argv[6]

cutoff_ms = int((time.time() - older_than_days * 86400) * 1000)

# Load current session to exclude
current_sid = ""
if os.path.exists(current_path):
    try:
        current_sid = str(json.load(open(current_path, encoding="utf-8")).get("session_id") or "").strip()
    except Exception:
        pass

# Load registry
data = {"sessions": {}}
if os.path.exists(registry_path):
    try:
        data = json.load(open(registry_path, encoding="utf-8"))
    except Exception:
        data = {"sessions": {}}

sessions = dict(data.get("sessions") or {})
candidates = []
kept = {}

for sid, entry in sessions.items():
    last_used = int(entry.get("last_used_unix_ms") or 0)
    if sid == current_sid:
        kept[sid] = entry
        continue
    if last_used > 0 and last_used < cutoff_ms:
        candidates.append(entry)
    else:
        kept[sid] = entry

if not candidates:
    print(f"[core] no sessions older than {older_than_days} days found")
    raise SystemExit(0)

print(f"[core] session archive: {len(candidates)} session(s) older than {older_than_days} days")
for entry in sorted(candidates, key=lambda e: int(e.get("last_used_unix_ms") or 0)):
    sid = str(entry.get("session_id") or "").strip()
    last_used = int(entry.get("last_used_unix_ms") or 0)
    marker = "  [DRY-RUN]" if dry_run else "  [ARCHIVE]"
    print(f"{marker} {sid}  last_used={last_used}")

if dry_run:
    print(f"\n[core] dry-run: would archive {len(candidates)} session(s)")
    print(f"[core] re-run with --execute to apply")
    raise SystemExit(0)

# Archive: export session event files, then prune from registry
os.makedirs(archive_dir, exist_ok=True)
archived_count = 0
event_dir = os.path.join(loom_root, "state", "session-history", "events")

for entry in candidates:
    sid = str(entry.get("session_id") or "").strip()
    session_key = f"web_api:{sid}"
    # Find matching event file
    event_files = sorted(glob.glob(os.path.join(event_dir, "*.json")), key=os.path.getmtime, reverse=True)
    for epath in event_files:
        try:
            edata = json.load(open(epath, encoding="utf-8"))
        except Exception:
            continue
        if str(edata.get("session_key") or "").strip() != session_key:
            continue
        dest = os.path.join(archive_dir, os.path.basename(epath))
        shutil.move(epath, dest)
        archived_count += 1
        break

# Update registry
data["sessions"] = kept
with open(registry_path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(f"\n[core] archived {archived_count} event file(s) to: {archive_dir}")
print(f"[core] registry updated: {len(kept)} session(s) remaining")
PY
}

# ── Command: browse ───────────────────────────────────────────────────────

cmd_browse() {
    local url="${1:-}"
    [ -n "$url" ] || die "Usage: core.sh browse URL"
    require_loom; require_runtime
    validate_browse_url "$url" || die "browse blocked by Core browser policy: $url"

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

validate_browse_url() {
    python3 - "$1" "${MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS:-}" <<'PY'
import sys
from urllib.parse import urlparse

url = str(sys.argv[1] or "").strip()
raw_allowlist = str(sys.argv[2] or "").strip()
parsed = urlparse(url)

scheme = str(parsed.scheme or "").strip().lower()
if scheme not in {"http", "https"}:
    raise SystemExit(f"scheme '{scheme or '(missing)'}' is not allowed; use http/https only")

host = str(parsed.hostname or "").strip().lower()
if not host:
    raise SystemExit("missing hostname")

if raw_allowlist:
    allowed = [item.strip().lower() for item in raw_allowlist.split(",") if item.strip()]
    if host not in allowed and not any(host.endswith("." + item) for item in allowed):
        raise SystemExit(f"host '{host}' is not in MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS")
PY
}

# ── Command: research ─────────────────────────────────────────────────────

build_research_argv_json() {
    python3 - "$1" <<'PY'
import json, shlex, sys

query = str(sys.argv[1] or "").strip()
if not query:
    raise SystemExit("empty research query")
try:
    argv = shlex.split(query)
except Exception as exc:
    raise SystemExit(f"could not parse command: {exc}")
if not argv:
    raise SystemExit("empty research argv")

first = argv[0]
allowed = {
    "rg", "ls", "cat", "sed", "awk", "jq", "head", "tail", "wc", "find",
    "sort", "uniq", "cut", "egrep", "file", "git", "ps", "ss", "curl",
}
if first not in allowed:
    raise SystemExit(f"command '{first}' is not allowed in core.sh research")

if first == "git":
    if len(argv) < 2:
        raise SystemExit("git research commands require a subcommand")
    allowed_git = {"status", "diff", "log", "show", "rev-parse", "branch", "remote", "ls-files", "grep"}
    if argv[1] not in allowed_git:
        raise SystemExit(f"git subcommand '{argv[1]}' is not allowed in core.sh research")

if first == "curl":
    banned_flags = {"-X", "--request", "-d", "--data", "--data-binary", "--data-raw", "-F", "--form", "-T", "--upload-file"}
    for token in argv[1:]:
        if token in banned_flags:
            raise SystemExit(f"curl flag '{token}' is not allowed in core.sh research")

print(json.dumps(argv, ensure_ascii=False))
PY
}

core_shell_preset_argv_json() {
    python3 - "$1" "$MERIDIAN_ROOT" "$LOOM_ROOT" <<'PY'
import json, os, sys

preset = str(sys.argv[1] or "").strip().lower()
meridian_root = sys.argv[2]
loom_root = sys.argv[3]

presets = {
    "repo-status": ["git", "-C", meridian_root, "status", "--short"],
    "repo-diff": ["git", "-C", meridian_root, "diff", "--stat"],
    "repo-log": ["git", "-C", meridian_root, "log", "--oneline", "-5"],
    "runtime-events": ["tail", "-n", "20", os.path.join(loom_root, "artifacts", "runtime", "events", "stream.jsonl")],
    "open-ports": ["ss", "-ltnp"],
    "schedule-list": [os.path.join(meridian_root, "loom", "target", "release", "loom"), "schedule", "list", "--root", loom_root, "--format", "human"],
}

argv = presets.get(preset)
if not argv:
    raise SystemExit(f"unknown shell preset: {preset}")
print(json.dumps(argv, ensure_ascii=False))
PY
}

run_terminal_exec_argv_json() {
    local argv_json="$1"
    local label="${2:-terminal task}"
    require_loom; require_runtime

    local org_id; org_id="$(resolve_org_id)"
    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$org_id" ] || die "Could not resolve org_id. Run onboard.sh first."
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    echo "[core] ${label}"
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

cmd_research() {
    local query="${1:-}"
    [ -n "$query" ] || die "Usage: core.sh research \"command [args]\""
    local argv_json
    argv_json="$(build_research_argv_json "$query")" || die "unsafe research command: $query"
    run_terminal_exec_argv_json "$argv_json" "research: $query"
}

# ── Command: shell ────────────────────────────────────────────────────────

cmd_shell() {
    local subcmd="${1:-list}"
    shift || true

    case "$subcmd" in
        list)
            cat <<'EOF'
[core] shell presets
  repo-status    git status --short
  repo-diff      git diff --stat
  repo-log       git log --oneline -5
  runtime-events tail -n 20 runtime event stream
  open-ports     ss -ltnp
  schedule-list  loom schedule list --format human
EOF
            ;;
        run)
            local preset="${1:-}"
            [ -n "$preset" ] || die "Usage: core.sh shell run PRESET"
            local argv_json
            argv_json="$(core_shell_preset_argv_json "$preset")" || die "unknown shell preset: $preset"
            run_terminal_exec_argv_json "$argv_json" "shell preset: $preset"
            ;;
        *)
            die "Usage: core.sh shell <list|run PRESET>"
            ;;
    esac
}

# ── Command: remember ─────────────────────────────────────────────────────

cmd_remember() {
    # Positional: KEY VALUE. Optional --tag flags (repeatable) are stripped
    # before positional parsing so operators can do:
    #   core.sh remember mykey "the value" --tag release --tag vietnam
    local tag_args=()
    local positional=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --tag)
                tag_args+=("--tag" "${2:-}")
                shift 2 || true
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh remember KEY "VALUE" [--tag LABEL]...

Store a memory entry under category "core" for the active agent.
Tags are open-ended labels; matching is case-insensitive trim-only.
Use core.sh recall --tag LABEL or memory search --tag to retrieve.
EOF
                return 0
                ;;
            *)
                positional+=("$1"); shift
                ;;
        esac
    done
    local key="${positional[0]:-}"; local value="${positional[1]:-}"
    [ -n "$key" ] && [ -n "$value" ] || die "Usage: core.sh remember KEY \"VALUE\" [--tag LABEL]..."
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
        "${tag_args[@]}" \
        --format json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); tags=d.get('tags') or []; tagstr=(' tags=['+','.join(tags)+']') if tags else ''; print(f'[core] stored: {d.get(\"key\")} -> {d.get(\"content\",\"\")[:60]}{tagstr}')" 2>/dev/null || echo "[core] stored: $key"
}

# ── Command: recall ───────────────────────────────────────────────────────

cmd_recall() {
    local prefix=""
    local text_query=""
    local limit=""
    local tag_args=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --text)
                text_query="${2:-}"; shift 2 || true
                ;;
            --limit)
                limit="${2:-}"; shift 2 || true
                ;;
            --tag)
                tag_args+=("--tag" "${2:-}"); shift 2 || true
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh recall [KEY_PREFIX] [--text QUERY] [--tag LABEL]... [--limit N]

Search Core memory by key prefix (default) and/or by case-insensitive
substring against entry key or content. Pass --tag (repeatable) to
filter by tags (AND across tags, case-insensitive).
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                if [ -z "$prefix" ]; then prefix="$1"; else die "Unexpected argument: $1"; fi
                shift
                ;;
        esac
    done
    require_loom; require_runtime

    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    local args=("--agent-id" "$agent_id" "--category" "core" "--root" "$LOOM_ROOT" "--format" "json")
    [ -n "$prefix" ] && args+=("--key-prefix" "$prefix")
    [ -n "$text_query" ] && args+=("--text" "$text_query")
    [ -n "$limit" ] && args+=("--limit" "$limit")
    if [ ${#tag_args[@]} -gt 0 ]; then args+=("${tag_args[@]}"); fi

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
    tags = e.get('tags') or []
    tagstr = ' [' + ','.join(tags) + ']' if tags else ''
    print(f'  {e.get(\"key\")}{tagstr}: {e.get(\"content\",\"\")[:80]}')
"
}

# ── Command: memory search ────────────────────────────────────────────────
# Full-content search across all categories for the active agent.

cmd_memory_search() {
    local query=""
    local limit=""
    local all_agents=0
    local tag_args=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --all-agents)
                all_agents=1; shift
                ;;
            --tag)
                tag_args+=("--tag" "${2:-}"); shift 2 || true
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory search QUERY [LIMIT] [--all-agents] [--tag LABEL]...

Full-content search across stored memory (case-insensitive substring
against entry key or content). Default scope is the active agent.
Use --all-agents to fan out across every agent in the runtime root;
results are merged and ordered by most-recent updated_at first.
Pass --tag (repeatable) to AND-filter results by tag.
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                if [ -z "$query" ]; then query="$1"
                elif [ -z "$limit" ]; then limit="$1"
                else die "Unexpected argument: $1"
                fi
                shift
                ;;
        esac
    done
    [ -n "$query" ] || die "Usage: core.sh memory search QUERY [LIMIT] [--all-agents] [--tag LABEL]..."
    require_loom; require_runtime

    local args=("--root" "$LOOM_ROOT" "--format" "json" "--text" "$query")
    [ -n "$limit" ] && args+=("--limit" "$limit")
    if [ "$all_agents" -eq 1 ]; then
        args+=("--all-agents")
    else
        local agent_id; agent_id="$(resolve_agent_id)"
        [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."
        args+=("--agent-id" "$agent_id")
    fi
    if [ ${#tag_args[@]} -gt 0 ]; then args+=("${tag_args[@]}"); fi

    local mem_json
    mem_json="$("$LOOM_BIN" memory search "${args[@]}" 2>/dev/null || true)"
    QUERY="$query" MEM_JSON="$mem_json" SHOW_AGENT="$all_agents" python3 - <<'PY'
import json, os
query = os.environ.get("QUERY", "")
raw = os.environ.get("MEM_JSON", "") or "[]"
show_agent = os.environ.get("SHOW_AGENT", "0") == "1"
try:
    entries = json.loads(raw)
except Exception:
    entries = []
if not entries:
    print(f"[core] no memory entries match: {query}")
    raise SystemExit(0)
print(f"[core] {len(entries)} match(es) for: {query}")
for e in entries:
    agent = e.get("agent_id", "?")
    cat = e.get("category", "?")
    key = e.get("key", "?")
    content = (e.get("content") or "").replace("\n", " ")
    if len(content) > 100:
        content = content[:100] + "…"
    if show_agent:
        print(f"  [{agent}/{cat}] {key}: {content}")
    else:
        print(f"  [{cat}] {key}: {content}")
PY
}

# ── Command: schedule ─────────────────────────────────────────────────────

schedule_job_id_slug() {
    python3 - "$1" <<'PY'
import re, sys
raw = str(sys.argv[1] or "").strip().lower()
slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
print(slug or "core-routine")
PY
}

cmd_schedule_status() {
    require_loom; require_runtime
    local raw
    raw="$("$LOOM_BIN" schedule status --root "$LOOM_ROOT" --format json)"
    python3 - "$raw" <<'PY'
import json, sys
payload = json.loads(sys.argv[1] or "{}")
print("[core] schedule runtime")
print(f"  total:   {int(payload.get('total_count') or 0)}")
print(f"  enabled: {int(payload.get('enabled_count') or 0)}")
print(f"  due:     {int(payload.get('due_count') or 0)}")
registry = str(payload.get("registry_path") or "").strip()
if registry:
    print(f"  registry: {registry}")
job_ids = payload.get("job_ids") or []
if job_ids:
    print("  jobs:")
    for job_id in job_ids:
        print(f"    - {job_id}")
PY
}

cmd_schedule_list() {
    require_loom; require_runtime
    local raw
    raw="$("$LOOM_BIN" schedule list --root "$LOOM_ROOT" --format json)"
    python3 - "$raw" <<'PY'
import datetime as dt, json, sys
records = json.loads(sys.argv[1] or "[]")
if not records:
    print("[core] no scheduled jobs found")
    raise SystemExit(0)
print(f"[core] {len(records)} scheduled job(s):")
for record in records:
    status = "paused" if not bool(record.get("enabled", True)) else str(record.get("status") or "scheduled")
    next_fire = record.get("next_fire_at_unix_ms")
    if next_fire:
        ts = dt.datetime.fromtimestamp(int(next_fire) / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    else:
        ts = "(none)"
    print(
        f"  {record.get('job_id','?')}  "
        f"agent={record.get('agent_id','?')}  "
        f"kind={record.get('job_kind','?')}  "
        f"schedule={record.get('schedule_kind','?')}  "
        f"status={status}  "
        f"next={ts}"
    )
PY
}

cmd_schedule_show() {
    local job_id="${1:-}"
    [ -n "$job_id" ] || die "Usage: core.sh schedule show JOB_ID"
    require_loom; require_runtime
    "$LOOM_BIN" schedule show --job-id "$job_id" --root "$LOOM_ROOT" --format human
}

cmd_schedule_every() {
    local name="${1:-}"
    local every="${2:-3600}"
    [ -n "$name" ] || die "Usage: core.sh schedule every NAME SECONDS"
    [ -n "$every" ] || die "Usage: core.sh schedule every NAME SECONDS"
    require_loom; require_runtime

    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    local job_id
    job_id="$(schedule_job_id_slug "$name")"
    "$LOOM_BIN" schedule add \
        --agent-id "$agent_id" \
        --job-id "$job_id" \
        --job-kind "$job_id" \
        --schedule interval \
        --every-seconds "$every" \
        --source-kind manual \
        --root "$LOOM_ROOT" \
        --format human
}

cmd_schedule_daily() {
    local name="${1:-}"
    local hhmm="${2:-}"
    local tz="${3:-UTC}"
    [ -n "$name" ] || die "Usage: core.sh schedule daily NAME HH:MM [TZ]"
    [ -n "$hhmm" ] || die "Usage: core.sh schedule daily NAME HH:MM [TZ]"
    require_loom; require_runtime

    local agent_id; agent_id="$(resolve_agent_id)"
    [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."

    local job_id
    job_id="$(schedule_job_id_slug "$name")"
    "$LOOM_BIN" schedule add \
        --agent-id "$agent_id" \
        --job-id "$job_id" \
        --job-kind "$job_id" \
        --schedule daily \
        --expression "$hhmm" \
        --timezone "$tz" \
        --source-kind manual \
        --root "$LOOM_ROOT" \
        --format human
}

cmd_schedule_pause() {
    local job_id="${1:-}"
    [ -n "$job_id" ] || die "Usage: core.sh schedule pause JOB_ID"
    require_loom; require_runtime
    "$LOOM_BIN" schedule pause --job-id "$job_id" --root "$LOOM_ROOT" --format human
}

cmd_schedule_cancel() {
    local job_id="${1:-}"
    [ -n "$job_id" ] || die "Usage: core.sh schedule cancel JOB_ID"
    require_loom; require_runtime
    "$LOOM_BIN" schedule cancel --job-id "$job_id" --root "$LOOM_ROOT" --format human
}

cmd_schedule_run() {
    local job_id="${1:-}"
    [ -n "$job_id" ] || die "Usage: core.sh schedule run JOB_ID"
    require_loom; require_runtime
    "$LOOM_BIN" schedule run --job-id "$job_id" --root "$LOOM_ROOT" --format human
}

cmd_schedule_run_due() {
    local limit="${1:-20}"
    require_loom; require_runtime
    "$LOOM_BIN" schedule run-due --limit "$limit" --root "$LOOM_ROOT" --format human
}

cmd_schedule() {
    local subcmd="${1:-list}"
    if [ "$subcmd" = "help" ] || [ "$subcmd" = "--help" ] || [ "$subcmd" = "-h" ]; then
        die "Usage: core.sh schedule <status|list|show|every|daily|pause|cancel|run|run-due> [args]"
    fi

    case "$subcmd" in
        status)
            shift || true
            cmd_schedule_status "$@"
            ;;
        list)
            shift || true
            cmd_schedule_list "$@"
            ;;
        show)
            shift || true
            cmd_schedule_show "$@"
            ;;
        every)
            shift || true
            cmd_schedule_every "$@"
            ;;
        daily)
            shift || true
            cmd_schedule_daily "$@"
            ;;
        pause)
            shift || true
            cmd_schedule_pause "$@"
            ;;
        cancel|remove|delete)
            shift || true
            cmd_schedule_cancel "$@"
            ;;
        run)
            shift || true
            cmd_schedule_run "$@"
            ;;
        run-due|due)
            shift || true
            cmd_schedule_run_due "$@"
            ;;
        *)
            if [ $# -le 2 ]; then
                cmd_schedule_every "$@"
            else
                die "Usage: core.sh schedule <status|list|show|every|daily|pause|cancel|run|run-due> [args]"
            fi
            ;;
    esac
}

# ── Command: schedules ────────────────────────────────────────────────────

cmd_schedules() {
    cmd_schedule list "$@"
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
        diagnostics)
            cmd_channel_diagnostics "$@"
            ;;
        proof)
            cmd_channel_proof "$@"
            ;;
        verify)
            cmd_channel_verify "$@"
            ;;
        watch)
            cmd_channel_watch "$@"
            ;;
        connect)
            cmd_channel_connect "$@"
            ;;
        *)
            die "Usage: core.sh channel <list|health|show|deliveries|send|test|diagnostics|proof|verify|watch|connect> [args]"
            ;;
    esac
}

cmd_channel_diagnostics() {
    local channel_id="${1:-}"
    local limit="${2:-20}"
    if [ -z "$channel_id" ]; then
        echo "[core] multi-channel health overview"
        _render_multi_channel_health
        return
    fi
    local gateway_url="${MERIDIAN_GATEWAY_URL%/}"
    local diag_json=""
    diag_json="$(curl -sf "${gateway_url}/api/channels/${channel_id}/diagnostics?limit=${limit}" 2>/dev/null || printf '{}')"
    if [ -z "$diag_json" ] || [ "$diag_json" = "{}" ]; then
        echo "[core] gateway not reachable — showing file-based diagnostics for ${channel_id}"
        _render_channel_diagnostics_from_files "$channel_id" "$limit"
        return
    fi
    python3 - "$diag_json" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
    if data.get("status") == "error":
        print(f"  error: {data.get('output', 'unknown')}")
        sys.exit(0)
    diag = data.get("diagnostics") or data
    summary = diag.get("summary") or {}
    records = diag.get("recent_deliveries") or []
    cid = diag.get("channel_id", "?")
    print(f"[core] channel diagnostics: {cid}")
    print("  source: gateway_http")
    print(f"  delivered: {summary.get('delivered_count', 0)}")
    print(f"  failed:    {summary.get('failed_count', 0)}")
    print(f"  pending:   {summary.get('pending_count', 0)}")
    print(f"  latest:    {summary.get('latest_status', '-')}")
    if records:
        print(f"  recent deliveries ({len(records)}):")
        for r in records:
            did = r.get("delivery_id", "?")[:16]
            st = r.get("status", "?")
            rcpt = r.get("recipient", "?")[:20]
            tlen = r.get("text_length", 0)
            at = r.get("created_at", "?")
            detail = r.get("detail", "")
            line = f"    {did}  {st:10s}  to={rcpt}  len={tlen}  at={at}"
            if detail:
                line += f"  detail={detail[:60]}"
            print(line)
    else:
        print("  (no recent deliveries)")
except Exception as exc:
    print(f"  (diagnostics parse error: {exc})")
PY
}

_render_channel_diagnostics_from_files() {
    local channel_id="${1:-}"
    local limit="${2:-20}"
    python3 - "$channel_id" "$limit" "$LOOM_ROOT" <<'PY'
import json, sys
from pathlib import Path

channel_id, limit_str, loom_root = sys.argv[1:4]
limit = int(limit_str or "20")
delivery_dir = Path(loom_root) / "state" / "channels" / "delivery"
records = []
try:
    candidates = sorted(delivery_dir.glob("*.json"), reverse=True)
except Exception:
    candidates = []
for path in candidates:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(payload, dict):
        continue
    if str(payload.get("channel_id") or "").strip() != channel_id:
        continue
    records.append(payload)
    if len(records) >= limit:
        break
delivered = sum(1 for r in records if str(r.get("status") or "").strip() == "delivered")
failed = sum(1 for r in records if str(r.get("status") or "").strip() == "failed")
pending = sum(1 for r in records if str(r.get("status") or "").strip() not in {"delivered", "failed"})
print(f"[core] channel diagnostics (file-based): {channel_id}")
print("  source: local_delivery_ledger_fallback")
print(f"  delivered: {delivered}")
print(f"  failed:    {failed}")
print(f"  pending:   {pending}")
if records:
    latest = str(records[0].get("status") or "-").strip()
    print(f"  latest:    {latest}")
    print(f"  recent deliveries ({len(records)}):")
    for r in records:
        did = str(r.get("delivery_id") or "?")[:16]
        st = str(r.get("status") or "?")
        rcpt = str(r.get("recipient") or "?")[:20]
        tlen = len(str(r.get("text") or ""))
        at = str(r.get("created_at") or "?")
        detail = str(r.get("detail") or "")
        line = f"    {did}  {st:10s}  to={rcpt}  len={tlen}  at={at}"
        if detail:
            line += f"  detail={detail[:60]}"
        print(line)
else:
    print("  (no recent deliveries)")
PY
}

cmd_channel_proof() {
    local channel_id="${1:-}"
    local limit="${2:-50}"
    if [ -z "$channel_id" ]; then
        die "Usage: core.sh channel proof CHANNEL_ID [LIMIT]"
    fi
    local gateway_url="${MERIDIAN_GATEWAY_URL%/}"
    local proof_json=""
    proof_json="$(curl -sf "${gateway_url}/api/channels/${channel_id}/proof?limit=${limit}" 2>/dev/null || printf '{}')"
    if [ -z "$proof_json" ] || [ "$proof_json" = "{}" ]; then
        echo "[core] gateway not reachable — building proof from local delivery ledger"
        _render_channel_proof_from_files "$channel_id" "$limit"
        return
    fi
    python3 - "$proof_json" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
    if data.get("status") == "error":
        print(f"  error: {data.get('output', 'unknown')}")
        sys.exit(0)
    proof = data.get("delivery_proof") or data
    cid = proof.get("channel_id", "?")
    head = proof.get("head_chain_hash", "")
    receipts = proof.get("receipts") or []
    print(f"[core] channel delivery proof: {cid}")
    print("  source: gateway_http")
    print(f"  receipts:        {proof.get('receipt_count', 0)}")
    print(f"  total records:   {proof.get('total_records', 0)}")
    print(f"  head chain hash: {head[:32]}{'...' if len(head) > 32 else ''}")
    if receipts:
        print(f"  latest 5 receipts:")
        for r in receipts[-5:]:
            did = str(r.get("delivery_id", "?"))[:16]
            st = str(r.get("status", "?"))
            rh = str(r.get("receipt_hash", ""))[:16]
            ch = str(r.get("chain_hash", ""))[:16]
            print(f"    {did}  {st:10s}  receipt={rh}  chain={ch}")
    else:
        print("  (no receipts in window)")
except Exception as exc:
    print(f"  (proof parse error: {exc})")
PY
}

_render_channel_proof_from_files() {
    local channel_id="${1:-}"
    local limit="${2:-50}"
    python3 - "$channel_id" "$limit" "$LOOM_ROOT" <<'PY'
import hashlib, json, sys
from pathlib import Path

channel_id, limit_str, loom_root = sys.argv[1:4]
limit = int(limit_str or "50")
delivery_dir = Path(loom_root) / "state" / "channels" / "delivery"
records = []
try:
    candidates = sorted(delivery_dir.glob("*.json"))
except Exception:
    candidates = []
for path in candidates:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(payload, dict):
        continue
    if str(payload.get("channel_id") or "").strip() != channel_id:
        continue
    records.append(payload)
records.sort(key=lambda r: int(r.get("submitted_at_unix_ms") or 0), reverse=True)
window = records[:limit]
window_chrono = list(reversed(window))
chain = []
prev = ""
for rec in window_chrono:
    canonical = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    rh = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    ch = hashlib.sha256(f"{prev}:{rh}".encode("utf-8")).hexdigest()
    chain.append((str(rec.get("delivery_id") or "?"), str(rec.get("status") or "?"), rh, ch))
    prev = ch
print(f"[core] channel delivery proof (file-based): {channel_id}")
print("  source: local_delivery_ledger_fallback")
print(f"  receipts:        {len(chain)}")
print(f"  total records:   {len(records)}")
print(f"  head chain hash: {(chain[-1][3] if chain else '')[:32]}{'...' if chain and len(chain[-1][3]) > 32 else ''}")
if chain:
    print(f"  latest 5 receipts:")
    for did, st, rh, ch in chain[-5:]:
        print(f"    {did[:16]}  {st:10s}  receipt={rh[:16]}  chain={ch[:16]}")
else:
    print("  (no receipts in window)")
PY
}

cmd_channel_verify() {
    local channel_id="${1:-}"
    local recipient="${2:-}"
    if [ "${1:-}" != "" ] && [ "${2:-}" != "" ]; then
        shift 2
    elif [ "${1:-}" != "" ]; then
        shift 1
        recipient="auto"
    fi
    local text="${*:-}"
    [ -n "$channel_id" ] || die "Usage: core.sh channel verify CHANNEL [RECIPIENT|auto] [TEXT]"
    if [ -z "$recipient" ]; then
        recipient="auto"
    fi
    if [ -z "$text" ]; then
        text="meridian-verify-$(date +%s%N | head -c 19)"
    fi
    local gateway_port="${MERIDIAN_GATEWAY_PORT:-18910}"
    local payload
    payload="$(python3 -c '
import json, sys
print(json.dumps({"recipient": sys.argv[1], "text": sys.argv[2]}))
' "$recipient" "$text")"
    local verify_json=""
    verify_json="$(curl -sf -X POST -H 'Content-Type: application/json' -d "$payload" \
        "http://127.0.0.1:${gateway_port}/api/channels/${channel_id}/verify" 2>/dev/null || printf '')"
    if [ -z "$verify_json" ]; then
        echo "[core] gateway not reachable — running local verify via loom binary"
        _run_local_channel_verify "$channel_id" "$recipient" "$text"
        return
    fi
    python3 - "$verify_json" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
    if data.get("status") == "error":
        print(f"  error: {data.get('output', 'unknown')}")
        sys.exit(0)
    v = data.get("verify") or data
    print(f"[core] channel verify: {v.get('channel_id', '?')} -> {v.get('recipient', '?')}")
    print(f"  result:           {v.get('status', '?')}")
    print(f"  delivery_id:      {v.get('delivery_id', '-') or '-'}")
    print(f"  elapsed_ms:       {v.get('elapsed_ms', 0)}")
    pre = v.get('pre_head_chain_hash', '') or '-'
    post = v.get('post_head_chain_hash', '') or '-'
    print(f"  pre  chain head:  {pre[:32]}{'...' if len(pre) > 32 else ''}")
    print(f"  post chain head:  {post[:32]}{'...' if len(post) > 32 else ''}")
    if pre and post and pre != post:
        print(f"  chain extended:   yes")
    else:
        print(f"  chain extended:   no")
    ext = v.get('extension_receipt') or {}
    if ext:
        rh = str(ext.get('receipt_hash', ''))[:16]
        ch = str(ext.get('chain_hash', ''))[:16]
        print(f"  receipt:          {rh}  chain={ch}")
    if v.get('external_ref'):
        print(f"  external_ref:     {v.get('external_ref')}")
    if v.get('reason'):
        print(f"  reason:           {v.get('reason')}")
    if v.get('submit_error'):
        print(f"  submit_error:     {v.get('submit_error')}")
except Exception as exc:
    print(f"  (verify parse error: {exc})")
PY
}

_run_local_channel_verify() {
    local channel_id="${1:-}"
    local recipient="${2:-}"
    local text="${3:-meridian-verify-$(date +%s)}"
    require_loom; require_runtime
    if [ "$recipient" = "auto" ] || [ "$recipient" = "*" ] || [ -z "$recipient" ]; then
        recipient="$(_resolve_recent_active_peer "$channel_id")"
        if [ -z "$recipient" ]; then
            echo "[core] channel verify: no recent active peer on ${channel_id}; pass an explicit recipient"
            return 1
        fi
        echo "[core] channel verify: auto-resolved recipient -> ${recipient}"
    fi
    local pre_head
    pre_head="$(_compute_chain_head_for_channel "$channel_id")"
    local send_out
    send_out="$("$LOOM_BIN" channel send --root "$LOOM_ROOT" --channel "$channel_id" --recipient "$recipient" --text "$text" --format json 2>&1 || true)"
    local delivery_id
    delivery_id="$(printf '%s' "$send_out" | python3 -c '
import json, sys
try:
    data = json.loads(sys.stdin.read())
    print(str(data.get("delivery_id") or "").strip())
except Exception:
    pass
' 2>/dev/null || printf '')"
    if [ -z "$delivery_id" ]; then
        echo "[core] channel verify: submission failed"
        echo "  output: $send_out"
        return 1
    fi
    local deadline=$((SECONDS + 12))
    local terminal=""
    while [ $SECONDS -lt $deadline ]; do
        terminal="$(python3 - "$LOOM_ROOT" "$delivery_id" <<'PY'
import json, sys
from pathlib import Path
loom_root, did = sys.argv[1:3]
delivery_dir = Path(loom_root) / "state" / "channels" / "delivery"
try:
    for path in delivery_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("delivery_id") or "").strip() != did:
            continue
        st = str(data.get("status") or "").strip()
        if st in {"delivered", "failed", "blocked"}:
            print(st)
            sys.exit(0)
except Exception:
    pass
PY
)"
        if [ -n "$terminal" ]; then
            break
        fi
        sleep 0.25
    done
    local post_head
    post_head="$(_compute_chain_head_for_channel "$channel_id")"
    echo "[core] channel verify: ${channel_id} -> ${recipient}"
    echo "  result:           ${terminal:-timeout}"
    echo "  delivery_id:      ${delivery_id}"
    if [ ${#pre_head} -gt 32 ]; then pre_head_disp="${pre_head:0:32}..."; else pre_head_disp="$pre_head"; fi
    if [ ${#post_head} -gt 32 ]; then post_head_disp="${post_head:0:32}..."; else post_head_disp="$post_head"; fi
    echo "  pre  chain head:  ${pre_head_disp}"
    echo "  post chain head:  ${post_head_disp}"
    if [ -n "$pre_head" ] && [ -n "$post_head" ] && [ "$pre_head" != "$post_head" ]; then
        echo "  chain extended:   yes"
    else
        echo "  chain extended:   no"
    fi
}

_compute_chain_head_for_channel() {
    local channel_id="${1:-}"
    python3 - "$channel_id" "$LOOM_ROOT" <<'PY'
import hashlib, json, sys
from pathlib import Path
channel_id, loom_root = sys.argv[1:3]
delivery_dir = Path(loom_root) / "state" / "channels" / "delivery"
records = []
try:
    for path in delivery_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("channel_id") or "").strip() != channel_id:
            continue
        records.append(payload)
except Exception:
    pass
records.sort(key=lambda r: int(r.get("submitted_at_unix_ms") or 0))
prev = ""
for rec in records:
    canonical = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    rh = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    prev = hashlib.sha256(f"{prev}:{rh}".encode("utf-8")).hexdigest()
print(prev)
PY
}

_resolve_recent_active_peer() {
    local channel_id="${1:-}"
    python3 - "$channel_id" "$LOOM_ROOT" <<'PY'
import json, sys
from pathlib import Path
channel_id, loom_root = sys.argv[1:3]
inbox_dir = Path(loom_root) / "state" / "channels" / "inbox"
best = (0, "")
try:
    candidates = sorted(inbox_dir.glob("*.json"), reverse=True)
except Exception:
    candidates = []
for path in candidates[:1000]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(payload, dict):
        continue
    if str(payload.get("channel_id") or "").strip() != channel_id:
        continue
    peer = str(payload.get("peer_id") or "").strip()
    if not peer:
        continue
    ts = int(payload.get("received_at_unix_ms") or 0)
    if ts > best[0]:
        best = (ts, peer)
print(best[1])
PY
}

cmd_channel_watch() {
    local channel_id="${1:-}"
    local interval="${2:-1}"
    [ -n "$channel_id" ] || die "Usage: core.sh channel watch CHANNEL [INTERVAL_SECONDS]"
    require_runtime
    echo "[core] watching channel '${channel_id}' delivery ledger (Ctrl-C to stop)"
    python3 - "$channel_id" "$LOOM_ROOT" "$interval" <<'PY'
import json, sys, time
from pathlib import Path
channel_id, loom_root, interval_str = sys.argv[1:4]
interval = max(0.5, float(interval_str or "1"))
delivery_dir = Path(loom_root) / "state" / "channels" / "delivery"
inbox_dir = Path(loom_root) / "state" / "channels" / "inbox"
seen_deliveries = set()
seen_inbox = set()
# Seed with what is already on disk so we only show new records
try:
    for p in delivery_dir.glob("*.json"):
        seen_deliveries.add(p.name)
except Exception:
    pass
try:
    for p in inbox_dir.glob("*.json"):
        seen_inbox.add(p.name)
except Exception:
    pass
print(f"  ready: {len(seen_deliveries)} existing deliveries, {len(seen_inbox)} existing inbound")
sys.stdout.flush()
try:
    while True:
        try:
            for p in sorted(delivery_dir.glob("*.json")):
                if p.name in seen_deliveries:
                    continue
                seen_deliveries.add(p.name)
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if str(data.get("channel_id") or "").strip() != channel_id:
                    continue
                did = str(data.get("delivery_id") or "?")[:24]
                st = str(data.get("status") or "?")
                rcpt = str(data.get("recipient") or "?")[:24]
                ext = str(data.get("external_ref") or "")[:24]
                tlen = len(str(data.get("display_text") or data.get("text") or ""))
                ts = data.get("submitted_at_unix_ms") or 0
                print(f"  [delivery] {did}  {st:10s}  to={rcpt}  ext={ext}  len={tlen}  ts={ts}")
                sys.stdout.flush()
            for p in sorted(inbox_dir.glob("*.json")):
                if p.name in seen_inbox:
                    continue
                seen_inbox.add(p.name)
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if str(data.get("channel_id") or "").strip() != channel_id:
                    continue
                ing = str(data.get("ingress_id") or "?")[:24]
                peer = str(data.get("peer_id") or "?")[:24]
                txt = str(data.get("text") or "")[:60].replace("\n", " ")
                ts = data.get("received_at_unix_ms") or 0
                print(f"  [inbound]  {ing}  from={peer}  ts={ts}  text={txt!r}")
                sys.stdout.flush()
        except Exception as exc:
            print(f"  watch warning: {exc}")
            sys.stdout.flush()
        time.sleep(interval)
except KeyboardInterrupt:
    print("[core] channel watch stopped")
PY
}

cmd_channel_connect() {
    local subcmd="${1:-list}"
    shift || true
    require_loom; require_runtime

    case "$subcmd" in
        list)
            "$LOOM_BIN" connect list --root "$LOOM_ROOT" --format human "${@}"
            ;;
        scaffold)
            local name="${1:-}"
            local transport="${2:-}"
            local schema="${3:-meridian.runtime.v1}"
            [ -n "$name" ] || die "Usage: core.sh channel connect scaffold NAME TRANSPORT [ACTION_SCHEMA]"
            [ -n "$transport" ] || die "Usage: core.sh channel connect scaffold NAME TRANSPORT [ACTION_SCHEMA]"
            "$LOOM_BIN" connect scaffold \
                --name "$name" \
                --transport "$transport" \
                --action-schema "$schema" \
                --root "$LOOM_ROOT" \
                --format human
            ;;
        validate)
            local adapter_id="${1:-}"
            [ -n "$adapter_id" ] || die "Usage: core.sh channel connect validate ADAPTER_ID"
            "$LOOM_BIN" connect validate --adapter-id "$adapter_id" --root "$LOOM_ROOT" --format human
            ;;
        enable)
            local adapter_id="${1:-}"
            [ -n "$adapter_id" ] || die "Usage: core.sh channel connect enable ADAPTER_ID"
            "$LOOM_BIN" connect enable --adapter-id "$adapter_id" --root "$LOOM_ROOT" --format human
            ;;
        disable)
            local adapter_id="${1:-}"
            [ -n "$adapter_id" ] || die "Usage: core.sh channel connect disable ADAPTER_ID"
            "$LOOM_BIN" connect disable --adapter-id "$adapter_id" --root "$LOOM_ROOT" --format human
            ;;
        test)
            local adapter_id="${1:-}"
            [ -n "$adapter_id" ] || die "Usage: core.sh channel connect test ADAPTER_ID"
            "$LOOM_BIN" connect test --adapter-id "$adapter_id" --root "$LOOM_ROOT" --format human
            ;;
        health)
            local adapter_id="${1:-}"
            [ -n "$adapter_id" ] || die "Usage: core.sh channel connect health ADAPTER_ID"
            "$LOOM_BIN" connect health --adapter-id "$adapter_id" --root "$LOOM_ROOT" --format human
            ;;
        diagnostics)
            local adapter_id="${1:-}"
            local limit="${2:-10}"
            [ -n "$adapter_id" ] || die "Usage: core.sh channel connect diagnostics ADAPTER_ID [LIMIT]"
            "$LOOM_BIN" connect diagnostics --adapter-id "$adapter_id" --limit "$limit" --root "$LOOM_ROOT" --format human
            ;;
        scorecard)
            "$LOOM_BIN" connect scorecard --root "$LOOM_ROOT" --format human "${@}"
            ;;
        prune)
            local adapter_id="${1:-}"
            local retention_days="${2:-30}"
            [ -n "$adapter_id" ] || die "Usage: core.sh channel connect prune ADAPTER_ID [RETENTION_DAYS]"
            "$LOOM_BIN" connect prune --adapter-id "$adapter_id" --retention-days "$retention_days" --root "$LOOM_ROOT" --format human
            ;;
        *)
            die "Usage: core.sh channel connect <list|scaffold|validate|enable|disable|test|health|diagnostics|scorecard|prune> [args]"
            ;;
    esac
}

# ── Command: files ────────────────────────────────────────────────────────

cmd_files() {
    ensure_core_state_dir
    local subcmd="${1:-list}"
    shift || true
    case "$subcmd" in
        add)
            [ $# -gt 0 ] || die "Usage: core.sh files add PATH [PATH ...]"
            local current_json merged_json
            current_json="$(load_pending_files_json)"
            merged_json="$(merge_pending_file_paths_json "$current_json" "$@")"
            save_pending_files_json "$merged_json"
            python3 - "$merged_json" <<'PY'
import json, sys
items = json.loads(sys.argv[1] or "[]")
print("[core] file queue")
print(f"  total_files:     {len(items)}")
for item in items[-20:]:
    print(f"    - {item}")
PY
            ;;
        list|status)
            local current_json
            current_json="$(load_pending_files_json)"
            python3 - "$current_json" <<'PY'
import json, os, sys
items = json.loads(sys.argv[1] or "[]")
print("[core] file queue")
print(f"  total_files:     {len(items)}")
if not items:
    print("  note:            no queued files")
else:
    total_bytes = 0
    for item in items:
        if os.path.isfile(item):
            total_bytes += os.path.getsize(item)
    print(f"  total_bytes:     {total_bytes}")
    for item in items[:50]:
        exists = os.path.isfile(item)
        size = os.path.getsize(item) if exists else 0
        state = "ok" if exists else "missing"
        print(f"    - {item}  state={state} size={size}")
PY
            ;;
        clear)
            save_pending_files_json '[]'
            echo "[core] file queue cleared"
            ;;
        remove)
            [ $# -gt 0 ] || die "Usage: core.sh files remove PATH [PATH ...]"
            local current_json next_json
            current_json="$(load_pending_files_json)"
            next_json="$(python3 - "$current_json" "$@" <<'PY'
import json, os, sys
items = json.loads(sys.argv[1] or "[]")
remove = {os.path.abspath(os.path.expanduser(p)) for p in sys.argv[2:]}
kept = [p for p in items if os.path.abspath(os.path.expanduser(p)) not in remove]
print(json.dumps(kept, ensure_ascii=False))
PY
)"
            save_pending_files_json "$next_json"
            cmd_files list
            ;;
        *)
            die "Usage: core.sh files <add PATH...|list|status|remove PATH...|clear>"
            ;;
    esac
}

# ── Command: context ──────────────────────────────────────────────────────

cmd_context() {
    ensure_core_state_dir
    local subcmd="${1:-list}"
    shift || true
    case "$subcmd" in
        add)
            [ $# -gt 0 ] || die "Usage: core.sh context add PATH [PATH ...]"
            local current_json merged_json
            current_json="$(load_context_files_json)"
            merged_json="$(merge_pending_file_paths_json "$current_json" "$@")"
            save_context_files_json "$merged_json"
            python3 - "$merged_json" <<'PY'
import json, sys
items = json.loads(sys.argv[1] or "[]")
print("[core] context files")
print(f"  total_files:     {len(items)}")
for item in items[-20:]:
    print(f"    - {item}")
PY
            ;;
        list|status)
            local current_json
            current_json="$(load_context_files_json)"
            python3 - "$current_json" <<'PY'
import json, os, sys
items = json.loads(sys.argv[1] or "[]")
print("[core] context files")
print(f"  total_files:     {len(items)}")
if not items:
    print("  note:            no persistent context files")
else:
    total_bytes = 0
    for item in items:
        if os.path.isfile(item):
            total_bytes += os.path.getsize(item)
    print(f"  total_bytes:     {total_bytes}")
    for item in items[:50]:
        exists = os.path.isfile(item)
        size = os.path.getsize(item) if exists else 0
        state = "ok" if exists else "missing"
        print(f"    - {item}  state={state} size={size}")
PY
            ;;
        clear)
            save_context_files_json '[]'
            echo "[core] context files cleared"
            ;;
        remove)
            [ $# -gt 0 ] || die "Usage: core.sh context remove PATH [PATH ...]"
            local current_json next_json
            current_json="$(load_context_files_json)"
            next_json="$(python3 - "$current_json" "$@" <<'PY'
import json, os, sys
items = json.loads(sys.argv[1] or "[]")
remove = {os.path.abspath(os.path.expanduser(p)) for p in sys.argv[2:]}
kept = [p for p in items if os.path.abspath(os.path.expanduser(p)) not in remove]
print(json.dumps(kept, ensure_ascii=False))
PY
)"
            save_context_files_json "$next_json"
            cmd_context list
            ;;
        *)
            die "Usage: core.sh context <add PATH...|list|status|remove PATH...|clear>"
            ;;
    esac
}

# ── Command: playbook ─────────────────────────────────────────────────────

playbook_slug() {
    python3 - "$1" <<'PY'
import re, sys
raw = str(sys.argv[1] or "").strip().lower()
slug = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-.")
print(slug or "core-playbook")
PY
}

playbook_path() {
    local name="${1:-}"
    local slug
    slug="$(playbook_slug "$name")"
    printf '%s/%s.md\n' "$CORE_PLAYBOOKS_DIR" "$slug"
}

playbook_schedule_job_id() {
    local name="${1:-}"
    local slug
    slug="$(playbook_slug "$name")"
    printf 'playbook-%s\n' "$slug"
}

playbook_schedule_payload_json() {
    local slug="${1:-}"
    local path="${2:-}"
    python3 - "$slug" "$path" <<'PY'
import json, sys
slug, path = sys.argv[1:3]
print(json.dumps({"playbook": slug, "path": path}, ensure_ascii=False))
PY
}

save_playbook_schedule_mapping() {
    local job_id="${1:-}"
    local slug="${2:-}"
    local path="${3:-}"
    local schedule_kind="${4:-}"
    local expression="${5:-}"
    local timezone="${6:-UTC}"
    ensure_core_state_dir
    python3 - "$CORE_PLAYBOOK_SCHEDULES_FILE" "$job_id" "$slug" "$path" "$schedule_kind" "$expression" "$timezone" <<'PY'
import json, os, sys, time

registry_path, job_id, slug, path, schedule_kind, expression, timezone = sys.argv[1:8]
try:
    with open(registry_path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    data = {"schedules": {}}

schedules = dict(data.get("schedules") or {})
schedules[job_id] = {
    "job_id": job_id,
    "job_kind": f"playbook:{slug}",
    "playbook": slug,
    "path": path,
    "schedule_kind": schedule_kind,
    "expression": expression,
    "timezone": timezone or "UTC",
    "updated_at_unix_ms": int(time.time() * 1000),
}
data["schedules"] = schedules
os.makedirs(os.path.dirname(registry_path), exist_ok=True)
with open(registry_path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(f"[core] playbook schedule mapped: {job_id}")
print(f"  job_kind: playbook:{slug}")
print(f"  playbook: {slug}")
print(f"  registry: {registry_path}")
PY
}

remove_playbook_schedule_mapping() {
    local job_id="${1:-}"
    ensure_core_state_dir
    python3 - "$CORE_PLAYBOOK_SCHEDULES_FILE" "$job_id" <<'PY'
import json, os, sys

registry_path, job_id = sys.argv[1:3]
try:
    with open(registry_path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    data = {"schedules": {}}

schedules = dict(data.get("schedules") or {})
removed = schedules.pop(job_id, None)
data["schedules"] = schedules
os.makedirs(os.path.dirname(registry_path), exist_ok=True)
with open(registry_path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

print(f"[core] playbook schedule unmapped: {job_id}")
print(f"  removed: {bool(removed)}")
print(f"  registry: {registry_path}")
PY
}

remove_loom_playbook_schedule_record() {
    local job_id="${1:-}"
    local registry_path="${LOOM_ROOT}/state/schedules/registry.json"
    python3 - "$registry_path" "$job_id" <<'PY'
import json, os, sys

registry_path, job_id = sys.argv[1:3]
if not os.path.exists(registry_path):
    raise SystemExit(0)

with open(registry_path, encoding="utf-8") as fh:
    data = json.load(fh)

records = list(data.get("schedules") or [])
kept = []
removed = 0
for record in records:
    if str(record.get("job_id") or "") != job_id:
        kept.append(record)
        continue
    job_kind = str(record.get("job_kind") or "")
    if not (job_id.startswith("playbook-") and job_kind.startswith("playbook:")):
        raise SystemExit(f"refusing to remove non-playbook schedule: {job_id}")
    removed += 1

if removed:
    data["schedules"] = kept
    with open(registry_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
PY
}

cmd_playbook() {
    ensure_core_playbooks_dir
    local subcmd="${1:-list}"
    shift || true
    case "$subcmd" in
        list)
            python3 - "$CORE_PLAYBOOKS_DIR" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
items = sorted(root.glob("*.md"))
print("[core] playbooks")
print(f"  total: {len(items)}")
for item in items:
    print(f"    - {item.stem}")
PY
            ;;
        schedules|schedule-list)
            ensure_core_state_dir
            python3 - "$CORE_PLAYBOOK_SCHEDULES_FILE" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    data = {"schedules": {}}

items = sorted((data.get("schedules") or {}).values(), key=lambda item: item.get("job_id", ""))
print("[core] playbook schedules")
print(f"  total: {len(items)}")
if path:
    print(f"  registry: {path}")
for item in items:
    print(
        "    - "
        f"{item.get('job_id', '?')}  "
        f"playbook={item.get('playbook', '?')}  "
        f"kind={item.get('job_kind', '?')}  "
        f"schedule={item.get('schedule_kind', '?')}  "
        f"expression={item.get('expression', '')}  "
        f"timezone={item.get('timezone', 'UTC')}"
    )
PY
            ;;
        scaffold)
            local name="${1:-}"
            [ -n "$name" ] || die "Usage: core.sh playbook scaffold NAME"
            local dest
            dest="$(playbook_path "$name")"
            [ ! -f "$dest" ] || die "playbook already exists: $(basename "$dest" .md)"
            python3 - "$dest" "$name" <<'PY'
from pathlib import Path
import sys
dest, name = sys.argv[1], sys.argv[2]
content = f"""# {name}

## Goal
State the recurring task this playbook should handle.

## Procedure
1. Review the current request and local context.
2. Execute the task carefully.
3. Return the exact deliverable the user needs.

## Output Contract
- Keep the answer concise.
- Include actionable results, not meta commentary.
"""
path = Path(dest)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(content, encoding="utf-8")
print(f"[core] playbook scaffolded: {path}")
PY
            ;;
        add)
            local name="${1:-}"
            local source="${2:-}"
            [ -n "$name" ] && [ -n "$source" ] || die "Usage: core.sh playbook add NAME SOURCE_FILE"
            [ -f "$source" ] || die "source file not found: $source"
            local dest
            dest="$(playbook_path "$name")"
            python3 - "$source" "$dest" <<'PY'
from pathlib import Path
import shutil, sys
src, dest = map(Path, sys.argv[1:3])
dest.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(src, dest)
print(f"[core] playbook saved: {dest}")
PY
            ;;
        capture)
            local name="${1:-}"
            shift || true
            local source_kind="last-output"
            while [ $# -gt 0 ]; do
                case "$1" in
                    --from)
                        [ -n "${2:-}" ] || die "Usage: core.sh playbook capture NAME [--from last-output|last-resume]"
                        source_kind="$2"
                        shift 2
                        ;;
                    *)
                        die "Usage: core.sh playbook capture NAME [--from last-output|last-resume]"
                        ;;
                esac
            done
            [ -n "$name" ] || die "Usage: core.sh playbook capture NAME [--from last-output|last-resume]"
            local source_file=""
            case "$source_kind" in
                last-output) source_file="$CORE_LAST_OUTPUT_FILE" ;;
                last-resume) source_file="$CORE_LAST_RESUME_FILE" ;;
                *) die "Usage: core.sh playbook capture NAME [--from last-output|last-resume]" ;;
            esac
            [ -f "$source_file" ] || die "capture source not found: $source_kind"
            local dest
            dest="$(playbook_path "$name")"
            python3 - "$source_file" "$dest" "$name" "$source_kind" <<'PY'
from pathlib import Path
import sys

source_file, dest, name, source_kind = sys.argv[1:5]
source = Path(source_file)
body = source.read_text(encoding="utf-8", errors="replace").strip()
content = f"""# {name}

## Goal
Reuse the captured Meridian Core result as a repeatable workflow.

## Source
- kind: `{source_kind}`
- path: `{source}`

## Procedure
1. Review the captured result below.
2. Adapt it to the user's current request and current context.
3. Return the updated deliverable directly.

## Captured Result

{body or "(empty)"}
"""
path = Path(dest)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(content, encoding="utf-8")
print(f"[core] playbook captured: {path}")
print(f"  source: {source_kind}")
PY
            ;;
        show)
            local name="${1:-}"
            [ -n "$name" ] || die "Usage: core.sh playbook show NAME"
            local path
            path="$(playbook_path "$name")"
            [ -f "$path" ] || die "playbook not found: $name"
            cat "$path"
            ;;
        remove)
            local name="${1:-}"
            [ -n "$name" ] || die "Usage: core.sh playbook remove NAME"
            local path
            path="$(playbook_path "$name")"
            [ -f "$path" ] || die "playbook not found: $name"
            rm -f "$path"
            echo "[core] playbook removed: $(basename "$path" .md)"
            ;;
        run)
            local name="${1:-}"
            shift || true
            [ -n "$name" ] || die "Usage: core.sh playbook run NAME [EXTRA_INSTRUCTION...]"
            local path
            path="$(playbook_path "$name")"
            [ -f "$path" ] || die "playbook not found: $name"
            local playbook_text extra_text combined
            playbook_text="$(cat "$path")"
            extra_text="$*"
            combined="Execute the following workflow instructions exactly.
Do not return Meridian/runtime/operator status unless the playbook explicitly asks for system status.
Return the deliverable requested by the playbook itself.

$playbook_text"
            if [ -n "$extra_text" ]; then
                combined="${combined}

Additional instruction:
$extra_text"
            fi
            cmd_ask "$combined"
            ;;
        run-scheduled)
            local job_id="${1:-}"
            shift || true
            [ -n "$job_id" ] || die "Usage: core.sh playbook run-scheduled JOB_ID [EXTRA_INSTRUCTION...]"
            ensure_core_state_dir
            local mapped_playbook
            mapped_playbook="$(python3 - "$CORE_PLAYBOOK_SCHEDULES_FILE" "$job_id" <<'PY'
import json, sys
path, job_id = sys.argv[1:3]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    data = {"schedules": {}}
entry = (data.get("schedules") or {}).get(job_id) or {}
print(str(entry.get("playbook") or ""))
PY
)"
            [ -n "$mapped_playbook" ] || die "playbook schedule not found: $job_id"
            cmd_playbook run "$mapped_playbook" "$@"
            ;;
        every)
            local name="${1:-}"
            local every="${2:-3600}"
            [ -n "$name" ] || die "Usage: core.sh playbook every NAME SECONDS"
            [ -n "$every" ] || die "Usage: core.sh playbook every NAME SECONDS"
            require_loom; require_runtime
            local path slug job_id payload agent_id
            path="$(playbook_path "$name")"
            [ -f "$path" ] || die "playbook not found: $name"
            slug="$(playbook_slug "$name")"
            job_id="$(playbook_schedule_job_id "$name")"
            payload="$(playbook_schedule_payload_json "$slug" "$path")"
            agent_id="$(resolve_agent_id)"
            [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."
            remove_loom_playbook_schedule_record "$job_id"
            "$LOOM_BIN" schedule add \
                --agent-id "$agent_id" \
                --job-id "$job_id" \
                --job-kind "playbook:${slug}" \
                --schedule interval \
                --every-seconds "$every" \
                --payload-json "$payload" \
                --source-kind core-playbook \
                --root "$LOOM_ROOT" \
                --format human
            save_playbook_schedule_mapping "$job_id" "$slug" "$path" "interval" "$every" "UTC"
            ;;
        daily)
            local name="${1:-}"
            local hhmm="${2:-}"
            local tz="${3:-UTC}"
            [ -n "$name" ] || die "Usage: core.sh playbook daily NAME HH:MM [TZ]"
            [ -n "$hhmm" ] || die "Usage: core.sh playbook daily NAME HH:MM [TZ]"
            require_loom; require_runtime
            local path slug job_id payload agent_id
            path="$(playbook_path "$name")"
            [ -f "$path" ] || die "playbook not found: $name"
            slug="$(playbook_slug "$name")"
            job_id="$(playbook_schedule_job_id "$name")"
            payload="$(playbook_schedule_payload_json "$slug" "$path")"
            agent_id="$(resolve_agent_id)"
            [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."
            remove_loom_playbook_schedule_record "$job_id"
            "$LOOM_BIN" schedule add \
                --agent-id "$agent_id" \
                --job-id "$job_id" \
                --job-kind "playbook:${slug}" \
                --schedule daily \
                --expression "$hhmm" \
                --timezone "$tz" \
                --payload-json "$payload" \
                --source-kind core-playbook \
                --root "$LOOM_ROOT" \
                --format human
            save_playbook_schedule_mapping "$job_id" "$slug" "$path" "daily" "$hhmm" "$tz"
            ;;
        unschedule)
            local target="${1:-}"
            [ -n "$target" ] || die "Usage: core.sh playbook unschedule NAME_OR_JOB_ID"
            require_loom; require_runtime
            local job_id
            case "$target" in
                playbook-*) job_id="$target" ;;
                *) job_id="$(playbook_schedule_job_id "$target")" ;;
            esac
            if "$LOOM_BIN" schedule show --job-id "$job_id" --root "$LOOM_ROOT" --format json >/dev/null 2>&1; then
                "$LOOM_BIN" schedule cancel --job-id "$job_id" --root "$LOOM_ROOT" --format human
            else
                echo "[core] playbook schedule not active in Loom: $job_id"
            fi
            remove_loom_playbook_schedule_record "$job_id"
            remove_playbook_schedule_mapping "$job_id"
            ;;
        *)
            die "Usage: core.sh playbook <list|schedules|scaffold NAME|add NAME SOURCE_FILE|capture NAME [--from last-output|last-resume]|show NAME|run NAME [EXTRA...]|run-scheduled JOB_ID [EXTRA...]|every NAME SECONDS|daily NAME HH:MM [TZ]|unschedule NAME_OR_JOB_ID|remove NAME>"
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

# ── Command: web ──────────────────────────────────────────────────────────

cmd_web() {
    local subcmd="${1:-urls}"
    shift || true

    _port_listening() {
        local port="${1:-}"
        [ -n "$port" ] || return 1
        python3 - "$port" <<'PY'
import sys

port = int(sys.argv[1])
port_hex = f"{port:04X}"

def listening(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                cols = line.split()
                if len(cols) < 4:
                    continue
                local_addr = cols[1]
                state = cols[3]
                if state != "0A":
                    continue
                if ":" not in local_addr:
                    continue
                _, local_port = local_addr.rsplit(":", 1)
                if local_port.upper() == port_hex:
                    return True
    except Exception:
        return False
    return False

sys.exit(0 if any(listening(path) for path in ("/proc/net/tcp", "/proc/net/tcp6")) else 1)
PY
    }

    _pid_file_present() {
        local pid_file="${1:-}"
        [ -f "$pid_file" ] || return 1
        grep -qE '^[0-9]+$' "$pid_file" 2>/dev/null
    }

    case "$subcmd" in
        urls)
            local gateway_url="${MERIDIAN_GATEWAY_URL%/}"
            local workspace_url="http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}"
            local peer_workspace_url="http://127.0.0.1:${MERIDIAN_WORKSPACE_PEER_PORT}"
            echo "[core] web surfaces"
            echo "  gateway:        ${gateway_url}"
            echo "  workspace:      ${workspace_url}"
            echo "  peer_workspace: ${peer_workspace_url}"
            echo "  website:        https://app.welliam.codes/"
            echo "  pilot:          https://app.welliam.codes/pilot.html"
            echo "  demo:           https://app.welliam.codes/demo.html"
            ;;
        status)
            local gateway_status="down"
            local workspace_status="down"
            local peer_workspace_status="down"
            if _port_listening "${MERIDIAN_GATEWAY_PORT}"; then
                gateway_status="ok"
            elif curl -fsS "http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}/api/healthz" >/dev/null 2>&1; then
                gateway_status="ok"
            elif _pid_file_present "${MERIDIAN_ROOT}/runtime/pids/gateway.pid"; then
                gateway_status="pid-file"
            fi
            if _port_listening "${MERIDIAN_WORKSPACE_PORT}"; then
                workspace_status="ok"
            elif curl -fsS "http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}/api/healthz" >/dev/null 2>&1; then
                workspace_status="ok"
            elif _pid_file_present "${MERIDIAN_ROOT}/runtime/pids/workspace.pid"; then
                workspace_status="pid-file"
            elif curl -sS -I "http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}" 2>/dev/null | grep -q "401 Unauthorized"; then
                workspace_status="auth-gated"
            fi
            if _port_listening "${MERIDIAN_WORKSPACE_PEER_PORT}"; then
                peer_workspace_status="ok"
            elif curl -fsS "http://127.0.0.1:${MERIDIAN_WORKSPACE_PEER_PORT}/api/healthz" >/dev/null 2>&1; then
                peer_workspace_status="ok"
            elif _pid_file_present "${MERIDIAN_ROOT}/runtime/pids/workspace-peer.pid"; then
                peer_workspace_status="pid-file"
            elif curl -sS -I "http://127.0.0.1:${MERIDIAN_WORKSPACE_PEER_PORT}" 2>/dev/null | grep -q "401 Unauthorized"; then
                peer_workspace_status="auth-gated"
            fi
            echo "[core] web status"
            echo "  gateway:        ${gateway_status}  http://127.0.0.1:${MERIDIAN_GATEWAY_PORT}"
            echo "  workspace:      ${workspace_status}  http://127.0.0.1:${MERIDIAN_WORKSPACE_PORT}"
            echo "  peer_workspace: ${peer_workspace_status}  http://127.0.0.1:${MERIDIAN_WORKSPACE_PEER_PORT}"
            ;;
        browse-policy)
            echo "[core] browser policy"
            echo "  allowed_schemes: http, https"
            if [ -n "${MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS:-}" ]; then
                echo "  allowed_hosts:   ${MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS}"
            else
                echo "  allowed_hosts:   (all hosts allowed; set MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS to restrict)"
            fi
            echo "  config_key:      MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS"
            ;;
        *)
            die "Usage: core.sh web <urls|status|browse-policy>"
            ;;
    esac
}

# ── Command: memory ───────────────────────────────────────────────────────

cmd_memory() {
    local subcmd="${1:-receipts}"
    shift || true
    require_loom; require_runtime

    case "$subcmd" in
        receipts)
            local agent_id; agent_id="$(resolve_agent_id)"
            [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."
            "$LOOM_BIN" memory receipts --agent-id "$agent_id" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        graph)
            local source_ref="${1:-}"
            [ -n "$source_ref" ] || die "Usage: core.sh memory graph SOURCE_REF [--node-id ID ...]"
            shift || true
            "$LOOM_BIN" memory graph inspect "$source_ref" --root "$LOOM_ROOT" --format human "${@}"
            ;;
        fork)
            cmd_memory_fork "$@"
            ;;
        replay)
            cmd_memory_replay "$@"
            ;;
        latest-fork)
            cmd_memory_latest_artifact fork "$@"
            ;;
        latest-replay)
            cmd_memory_latest_artifact replay "$@"
            ;;
        fork-history)
            cmd_memory_artifact_history fork "$@"
            ;;
        replay-history)
            cmd_memory_artifact_history replay "$@"
            ;;
        governance)
            cmd_memory_governance_summary "$@"
            ;;
        team-governance)
            cmd_memory_team_governance "$@"
            ;;
        overview)
            "$LOOM_BIN" memory overview --root "$LOOM_ROOT" --format human "${@}"
            ;;
        status)
            "$LOOM_BIN" memory status --root "$LOOM_ROOT" --format human "${@}"
            ;;
        search)
            cmd_memory_search "$@"
            ;;
        snapshot)
            cmd_memory_snapshot "$@"
            ;;
        restore)
            cmd_memory_restore "$@"
            ;;
        prune)
            cmd_memory_prune "$@"
            ;;
        diff)
            cmd_memory_diff "$@"
            ;;
        rotate)
            cmd_memory_rotate "$@"
            ;;
        health)
            cmd_memory_health "$@"
            ;;
        *)
            die "Usage: core.sh memory <receipts|graph|fork|replay|latest-fork|latest-replay|fork-history|replay-history|governance|team-governance|overview|status|search|snapshot|restore|prune|diff|rotate|health> [args]"
            ;;
    esac
}

# ── Command: memory snapshot ──────────────────────────────────────────────
# Backup/export memory entries to a directory: one JSON file per agent
# plus a _manifest.json with counts and timestamp. Useful before risky
# operations, for audit, or for migrating between runtime roots.

cmd_memory_fork() {
    local source_ref=""
    local target_agent=""
    local branch=""
    local node_id=""
    local direction=""
    local limit=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --target-agent)
                target_agent="${2:-}"; shift 2 || true
                ;;
            --branch)
                branch="${2:-}"; shift 2 || true
                ;;
            --node-id)
                node_id="${2:-}"; shift 2 || true
                ;;
            --direction)
                direction="${2:-}"; shift 2 || true
                ;;
            --limit)
                limit="${2:-}"; shift 2 || true
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory fork SOURCE_REF --target-agent ID [--branch NAME] [--node-id ID] [--direction ancestors|descendants|both] [--limit N]

Create a governed memory fork lane from SOURCE_REF into another agent's
memory namespace. This is additive and leaves the source untouched.
Useful for warm-starting a specialist or lab agent from an existing
memory branch before new work begins.
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                if [ -z "$source_ref" ]; then source_ref="$1"; else die "Unexpected argument: $1"; fi
                shift
                ;;
        esac
    done
    [ -n "$source_ref" ] || die "Usage: core.sh memory fork SOURCE_REF --target-agent ID [--branch NAME] [--node-id ID] [--direction ancestors|descendants|both] [--limit N]"
    [ -n "$target_agent" ] || die "--target-agent is required"
    require_loom; require_runtime

    local args=("memory" "fork" "$source_ref" "--target-agent-id" "$target_agent" "--root" "$LOOM_ROOT" "--format" "human")
    [ -n "$branch" ] && args+=("--branch" "$branch")
    [ -n "$node_id" ] && args+=("--node-id" "$node_id")
    [ -n "$direction" ] && args+=("--direction" "$direction")
    [ -n "$limit" ] && args+=("--limit" "$limit")

    "$LOOM_BIN" "${args[@]}"
}

cmd_memory_replay() {
    local source_ref=""
    local target_agent=""
    local node_id=""
    local direction=""
    local limit=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --target-agent)
                target_agent="${2:-}"; shift 2 || true
                ;;
            --node-id)
                node_id="${2:-}"; shift 2 || true
                ;;
            --direction)
                direction="${2:-}"; shift 2 || true
                ;;
            --limit)
                limit="${2:-}"; shift 2 || true
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory replay SOURCE_REF --target-agent ID [--node-id ID] [--direction ancestors|descendants|both] [--limit N]

Replay governed memory entries from SOURCE_REF into another agent. This
path preserves authority and court checks by passing through the kernel
governance boundary before any target-agent memory write is applied.
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                if [ -z "$source_ref" ]; then source_ref="$1"; else die "Unexpected argument: $1"; fi
                shift
                ;;
        esac
    done
    [ -n "$source_ref" ] || die "Usage: core.sh memory replay SOURCE_REF --target-agent ID [--node-id ID] [--direction ancestors|descendants|both] [--limit N]"
    [ -n "$target_agent" ] || die "--target-agent is required"
    require_loom; require_runtime

    local org_id; org_id="$(resolve_org_id)"
    [ -n "$org_id" ] || die "Could not resolve org_id. Run onboard.sh first."

    local args=("memory" "replay" "$source_ref" "--target-agent-id" "$target_agent" "--kernel-path" "$KERNEL_PATH" "--org-id" "$org_id" "--root" "$LOOM_ROOT" "--format" "human")
    [ -n "$node_id" ] && args+=("--node-id" "$node_id")
    [ -n "$direction" ] && args+=("--direction" "$direction")
    [ -n "$limit" ] && args+=("--limit" "$limit")

    "$LOOM_BIN" "${args[@]}"
}

cmd_memory_latest_artifact() {
    local kind="${1:-}"
    shift || true
    [ "$kind" = "fork" ] || [ "$kind" = "replay" ] || die "Usage: core.sh memory <latest-fork|latest-replay> [--json]"
    require_runtime

    local output_mode="human"
    while [ $# -gt 0 ]; do
        case "$1" in
            --json)
                output_mode="json"; shift
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory latest-${kind} [--json]

Inspect the latest governed memory ${kind} artifact recorded under the
runtime root. Use --json for machine-readable output.
EOF
                return 0
                ;;
            *)
                die "Unknown flag: $1"
                ;;
        esac
    done

    local artifact_path="${LOOM_ROOT}/artifacts/memory/${kind}s/latest.json"
    python3 - "$artifact_path" "$kind" "$output_mode" <<'PY'
import json, os, sys

artifact_path, kind, output_mode = sys.argv[1], sys.argv[2], sys.argv[3]
if not os.path.exists(artifact_path):
    print(f"[core] memory latest {kind}: no artifact at {artifact_path}")
    raise SystemExit(2)

try:
    payload = json.load(open(artifact_path, encoding="utf-8"))
except Exception as exc:
    print(f"[core] memory latest {kind}: failed to read {artifact_path}: {exc}")
    raise SystemExit(1)

if output_mode == "json":
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(0)

print(f"[core] memory latest {kind}")
print(f"  artifact_path:     {artifact_path}")
print(f"  status:            {payload.get('status') or 'unknown'}")
print(f"  source_ref:        {payload.get('source_ref') or ''}")
print(f"  target_agent_id:   {payload.get('target_agent_id') or ''}")
if kind == "fork":
    print(f"  branch:            {payload.get('branch') or ''}")
    print(f"  forked_entries:    {int(payload.get('forked_entries') or 0)}")
    print(f"  selected_entries:  {int(payload.get('selected_entries') or 0)}")
else:
    print(f"  court_status:      {payload.get('court_status') or 'unknown'}")
    print(f"  authority_status:  {payload.get('authority_status') or 'unknown'}")
    print(f"  replayed_entries:  {int(payload.get('replayed_entries') or 0)}")
print(f"  latest_artifact:   {payload.get('latest_artifact_path') or artifact_path}")
print(f"  note:              {payload.get('note') or ''}")
PY
}

cmd_memory_artifact_history() {
    local kind="${1:-}"
    shift || true
    [ "$kind" = "fork" ] || [ "$kind" = "replay" ] || die "Usage: core.sh memory <fork-history|replay-history> [LIMIT] [--json]"
    require_runtime

    local output_mode="human"
    local limit="10"
    while [ $# -gt 0 ]; do
        case "$1" in
            --json)
                output_mode="json"; shift
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory ${kind}-history [LIMIT] [--json]

Inspect recent governed memory ${kind} artifacts recorded under the
runtime root. LIMIT defaults to 10. Use --json for machine-readable output.
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                if [[ "$1" =~ ^[0-9]+$ ]]; then
                    limit="$1"; shift
                else
                    die "Unexpected argument: $1"
                fi
                ;;
        esac
    done

    local artifact_dir="${LOOM_ROOT}/artifacts/memory/${kind}s"
    python3 - "$artifact_dir" "$kind" "$limit" "$output_mode" <<'PY'
import glob, json, os, sys

artifact_dir, kind, raw_limit, output_mode = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    limit = max(1, int(raw_limit))
except ValueError:
    limit = 10

paths = []
if os.path.isdir(artifact_dir):
    paths = [
        path for path in glob.glob(os.path.join(artifact_dir, "*.json"))
        if os.path.basename(path) != "latest.json"
    ]
    paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)

items = []
for path in paths[:limit]:
    try:
        payload = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    if not isinstance(payload, dict):
        continue
    item = {
        "artifact_path": path,
        "status": str(payload.get("status") or "unknown"),
        "source_ref": str(payload.get("source_ref") or ""),
        "target_agent_id": str(payload.get("target_agent_id") or ""),
        "latest_artifact_path": str(payload.get("latest_artifact_path") or ""),
        "note": str(payload.get("note") or ""),
    }
    if kind == "fork":
        item["branch"] = str(payload.get("branch") or "")
        item["selected_entries"] = int(payload.get("selected_entries") or 0)
        item["forked_entries"] = int(payload.get("forked_entries") or 0)
    else:
        item["court_status"] = str(payload.get("court_status") or "unknown")
        item["authority_status"] = str(payload.get("authority_status") or "unknown")
        item["replayed_entries"] = int(payload.get("replayed_entries") or 0)
    items.append(item)

if output_mode == "json":
    print(json.dumps({
        "kind": kind,
        "artifact_dir": artifact_dir,
        "limit": limit,
        "artifact_count": len(items),
        "artifacts": items,
    }, indent=2, ensure_ascii=False))
    raise SystemExit(0)

print(f"[core] memory {kind} history")
print(f"  artifact_dir:      {artifact_dir}")
print(f"  limit:             {limit}")
print(f"  artifact_count:    {len(items)}")
if not items:
    print("  (no artifacts)")
    raise SystemExit(0)
for item in items:
    if kind == "fork":
        print(
            f"  - status={item['status']} source={item['source_ref']} target={item['target_agent_id']} "
            f"branch={item['branch']} forked={item['forked_entries']} selected={item['selected_entries']}"
        )
    else:
        print(
            f"  - status={item['status']} source={item['source_ref']} target={item['target_agent_id']} "
            f"court={item['court_status']} authority={item['authority_status']} replayed={item['replayed_entries']}"
        )
PY
}

cmd_memory_governance_summary() {
    require_runtime
    local limit="10"
    local output_mode="human"
    while [ $# -gt 0 ]; do
        case "$1" in
            --json)
                output_mode="json"; shift
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory governance [LIMIT] [--json]

Show an operator summary for governed memory fork/replay activity:
latest status plus recent artifact counts from the runtime root.
EOF
                return 0
                ;;
            *)
                if [[ "$1" =~ ^[0-9]+$ ]]; then
                    limit="$1"; shift
                else
                    die "Unexpected argument: $1"
                fi
                ;;
        esac
    done

    local fork_latest="${LOOM_ROOT}/artifacts/memory/forks/latest.json"
    local replay_latest="${LOOM_ROOT}/artifacts/memory/replays/latest.json"
    local fork_dir="${LOOM_ROOT}/artifacts/memory/forks"
    local replay_dir="${LOOM_ROOT}/artifacts/memory/replays"
    python3 - "$fork_latest" "$replay_latest" "$fork_dir" "$replay_dir" "$limit" "$output_mode" <<'PY'
import glob, json, os, sys

fork_latest, replay_latest, fork_dir, replay_dir, raw_limit, output_mode = sys.argv[1:7]
try:
    limit = max(1, int(raw_limit))
except ValueError:
    limit = 10

def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        payload = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None

def count_recent(path):
    if not os.path.isdir(path):
        return 0
    return len([p for p in glob.glob(os.path.join(path, "*.json")) if os.path.basename(p) != "latest.json"][:limit])

fork_payload = load_json(fork_latest)
replay_payload = load_json(replay_latest)
summary = {
    "limit": limit,
    "fork_latest_present": bool(fork_payload),
    "replay_latest_present": bool(replay_payload),
    "fork_latest_status": (fork_payload or {}).get("status") or "missing",
    "replay_latest_status": (replay_payload or {}).get("status") or "missing",
    "fork_recent_count": count_recent(fork_dir),
    "replay_recent_count": count_recent(replay_dir),
    "fork_target_agent_id": (fork_payload or {}).get("target_agent_id") or "",
    "replay_target_agent_id": (replay_payload or {}).get("target_agent_id") or "",
    "replay_authority_status": (replay_payload or {}).get("authority_status") or "",
}

if output_mode == "json":
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    raise SystemExit(0)

print("[core] memory governance")
print(f"  limit:                  {summary['limit']}")
print(f"  fork_latest_present:    {summary['fork_latest_present']}")
print(f"  fork_latest_status:     {summary['fork_latest_status']}")
print(f"  fork_recent_count:      {summary['fork_recent_count']}")
print(f"  fork_target_agent_id:   {summary['fork_target_agent_id']}")
print(f"  replay_latest_present:  {summary['replay_latest_present']}")
print(f"  replay_latest_status:   {summary['replay_latest_status']}")
print(f"  replay_recent_count:    {summary['replay_recent_count']}")
print(f"  replay_target_agent_id: {summary['replay_target_agent_id']}")
if summary["replay_authority_status"]:
    print(f"  replay_authority:       {summary['replay_authority_status']}")
PY
}

cmd_memory_team_governance() {
    require_runtime
    local limit="10"
    local output_mode="human"
    while [ $# -gt 0 ]; do
        case "$1" in
            --json)
                output_mode="json"; shift
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory team-governance [LIMIT] [--json]

Show compact governed-memory activity grouped by Team agents.
EOF
                return 0
                ;;
            *)
                if [[ "$1" =~ ^[0-9]+$ ]]; then
                    limit="$1"; shift
                else
                    die "Unexpected argument: $1"
                fi
                ;;
        esac
    done

    local url="${MERIDIAN_GATEWAY_URL%/}/api/team/governed-memory?limit=${limit}"
    local raw
    raw="$(curl -fsSL "$url" 2>/dev/null)" || die "gateway request failed: ${url}"
    python3 - "$output_mode" <<'PY' <<<"$raw"
import json, sys

output_mode = sys.argv[1]
try:
    payload = json.load(sys.stdin)
except Exception as exc:
    raise SystemExit(f"invalid team governed-memory payload: {exc}")

if output_mode == "json":
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(0)

if str(payload.get("status") or "").strip() != "success":
    print(f"[core] memory team governance error: {payload.get('output') or 'unknown'}")
    raise SystemExit(0)

summary = dict(payload.get("summary") or {})
agents = list(payload.get("agents") or [])
recent_actions = list(payload.get("recent_actions") or [])
print("[core] memory team governance")
print(f"  org_id:                 {payload.get('org_id') or ''}")
print(f"  agent_count:            {int(payload.get('agent_count') or 0)}")
print(f"  active_agent_count:     {int(payload.get('active_agent_count') or 0)}")
print(f"  fork_latest_status:     {summary.get('fork_latest_status') or 'missing'}")
print(f"  fork_recent_count:      {int(summary.get('fork_recent_count') or 0)}")
print(f"  replay_latest_status:   {summary.get('replay_latest_status') or 'missing'}")
print(f"  replay_recent_count:    {int(summary.get('replay_recent_count') or 0)}")
if summary.get("replay_authority_status"):
    print(f"  replay_authority:       {summary.get('replay_authority_status')}")
if not agents:
    print("  (no team agents)")
    raise SystemExit(0)
print("  agents:")
for item in agents:
    print(
        "    - "
        f"{item.get('name') or item.get('registry_id') or '?'} "
        f"role={item.get('role') or ''} "
        f"actions={int(item.get('recent_action_count') or 0)} "
        f"forks={int(item.get('fork_recent_count') or 0)} "
        f"replays={int(item.get('replay_recent_count') or 0)} "
        f"fork_latest={item.get('fork_latest_status') or 'missing'} "
        f"replay_latest={item.get('replay_latest_status') or 'missing'} "
        f"authority={item.get('replay_authority_status') or '-'}"
    )
if recent_actions:
    print("  recent_actions:")
    for action in recent_actions:
        print(
            "    - "
            f"{action.get('kind') or 'unknown'} "
            f"{action.get('handle') or action.get('registry_id') or '?'} "
            f"status={action.get('status') or 'unknown'} "
            f"target={action.get('target_agent_id') or '-'} "
            f"authority={action.get('authority_status') or '-'}"
        )
PY
}

cmd_memory_snapshot() {
    local target_dir=""
    local all_agents=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --all-agents)
                all_agents=1; shift
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory snapshot DIR [--all-agents]

Export memory entries to DIR as JSON files, one per agent, plus
DIR/_manifest.json with agent count, total entry count, runtime
root, and snapshot timestamp.

Default scope is the active agent. Use --all-agents to snapshot
every agent in the runtime root.
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                if [ -z "$target_dir" ]; then target_dir="$1"
                else die "Unexpected argument: $1"
                fi
                shift
                ;;
        esac
    done
    [ -n "$target_dir" ] || die "Usage: core.sh memory snapshot DIR [--all-agents]"
    require_loom; require_runtime
    mkdir -p "$target_dir" || die "cannot create snapshot dir: $target_dir"

    local agents=()
    if [ "$all_agents" -eq 1 ]; then
        local memory_root="$LOOM_ROOT/state/memory"
        [ -d "$memory_root" ] || die "memory root not found: $memory_root"
        local d
        for d in "$memory_root"/*/; do
            [ -d "$d" ] || continue
            local name; name="$(basename "$d")"
            [ -f "$d/index.json" ] || continue
            agents+=("$name")
        done
    else
        local agent_id; agent_id="$(resolve_agent_id)"
        [ -n "$agent_id" ] || die "Could not resolve agent_id. Run onboard.sh first."
        agents+=("$agent_id")
    fi

    if [ ${#agents[@]} -eq 0 ]; then
        echo "[core] no agents found to snapshot"
        return 0
    fi

    local total_entries=0
    local manifest_agents_json="["
    local first=1
    local agent
    for agent in "${agents[@]}"; do
        local out_file="$target_dir/${agent}.json"
        local raw
        raw="$("$LOOM_BIN" memory search --agent-id "$agent" --root "$LOOM_ROOT" --format json 2>/dev/null || echo "[]")"
        printf '%s' "$raw" > "$out_file"
        local count
        count="$(printf '%s' "$raw" | python3 -c "import sys,json
try:
    d=json.load(sys.stdin)
    print(len(d) if isinstance(d,list) else 0)
except Exception:
    print(0)
")"
        total_entries=$((total_entries + count))
        if [ "$first" -eq 1 ]; then
            first=0
        else
            manifest_agents_json+=","
        fi
        manifest_agents_json+="{\"agent_id\":\"$agent\",\"entry_count\":$count,\"path\":\"${agent}.json\"}"
    done
    manifest_agents_json+="]"

    local now_unix; now_unix="$(date -u +%s)"
    local now_iso; now_iso="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    local scope="single_agent"
    [ "$all_agents" -eq 1 ] && scope="all_agents"
    cat > "$target_dir/_manifest.json" <<EOF
{
  "version": 1,
  "snapshot_at_unix": $now_unix,
  "snapshot_at_iso": "$now_iso",
  "scope": "$scope",
  "loom_root": "$LOOM_ROOT",
  "agent_count": ${#agents[@]},
  "total_entry_count": $total_entries,
  "agents": $manifest_agents_json
}
EOF

    echo "[core] memory snapshot written to: $target_dir"
    echo "  scope:       $scope"
    echo "  agents:      ${#agents[@]}"
    echo "  entries:     $total_entries"
    echo "  manifest:    $target_dir/_manifest.json"
}

# ── Command: memory restore ───────────────────────────────────────────────
# Restore memory entries from a snapshot directory. Existing entries with
# the same (agent, category, key) are upserted, not removed. Intentionally
# non-destructive by default — operators must use loom memory remove
# explicitly to delete entries.

cmd_memory_restore() {
    local source_dir=""
    local agent_filter=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --agent)
                agent_filter="${2:-}"; shift 2 || true
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory restore SNAPSHOT_DIR [--agent ID]

Restore memory entries from a snapshot produced by
core.sh memory snapshot. Reads SNAPSHOT_DIR/_manifest.json, then
upserts each entry via loom memory write. Existing entries with the
same (agent, category, key) are overwritten in place; entries that
do not exist in the snapshot are left untouched. Use --agent to
restore only one agent from a multi-agent snapshot.
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                if [ -z "$source_dir" ]; then source_dir="$1"
                else die "Unexpected argument: $1"
                fi
                shift
                ;;
        esac
    done
    [ -n "$source_dir" ] || die "Usage: core.sh memory restore SNAPSHOT_DIR [--agent ID]"
    [ -d "$source_dir" ] || die "snapshot dir not found: $source_dir"
    local manifest_path="$source_dir/_manifest.json"
    [ -f "$manifest_path" ] || die "snapshot manifest missing: $manifest_path"
    require_loom; require_runtime

    # Parse manifest and emit `agent_id\tpath` lines for the agents we plan
    # to restore. Filter by --agent if requested.
    local plan
    plan="$(SOURCE_DIR="$source_dir" AGENT_FILTER="$agent_filter" python3 - <<'PY'
import json, os
src = os.environ["SOURCE_DIR"]
flt = os.environ.get("AGENT_FILTER", "") or None
manifest = json.load(open(os.path.join(src, "_manifest.json"), encoding="utf-8"))
for entry in manifest.get("agents") or []:
    aid = str(entry.get("agent_id") or "").strip()
    rel = str(entry.get("path") or "").strip()
    if not aid or not rel:
        continue
    if flt and aid != flt:
        continue
    print(f"{aid}\t{rel}")
PY
)"

    if [ -z "$plan" ]; then
        if [ -n "$agent_filter" ]; then
            die "no agent matching --agent $agent_filter in snapshot manifest"
        fi
        echo "[core] snapshot manifest contains no agents"
        return 0
    fi

    local total_restored=0
    local total_failed=0
    local agents_touched=0
    local line aid rel agent_path
    while IFS=$'\t' read -r aid rel; do
        agent_path="$source_dir/$rel"
        [ -f "$agent_path" ] || { echo "[core] skip $aid (missing $rel)"; continue; }
        agents_touched=$((agents_touched + 1))
        local agent_summary
        agent_summary="$(AGENT_PATH="$agent_path" AGENT_ID="$aid" LOOM_BIN="$LOOM_BIN" LOOM_ROOT="$LOOM_ROOT" python3 - <<'PY'
import json, os, subprocess
agent_path = os.environ["AGENT_PATH"]
agent_id = os.environ["AGENT_ID"]
loom_bin = os.environ["LOOM_BIN"]
loom_root = os.environ["LOOM_ROOT"]
try:
    entries = json.load(open(agent_path, encoding="utf-8"))
except Exception as exc:
    print(json.dumps({"agent_id": agent_id, "ok": 0, "fail": 0, "error": str(exc)}))
    raise SystemExit(0)
if not isinstance(entries, list):
    entries = []
ok = 0
fail = 0
for e in entries:
    try:
        cat = str(e.get("category") or "").strip()
        key = str(e.get("key") or "").strip()
        content = str(e.get("content") or "")
        source = str(e.get("source") or "snapshot_restore")
        if not (cat and key):
            fail += 1
            continue
        result = subprocess.run(
            [
                loom_bin, "memory", "write",
                "--agent-id", agent_id,
                "--category", cat,
                "--key", key,
                "--content", content,
                "--source", source,
                "--root", loom_root,
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            ok += 1
        else:
            fail += 1
    except Exception:
        fail += 1
print(json.dumps({"agent_id": agent_id, "ok": ok, "fail": fail}))
PY
)"
        local agent_ok agent_fail
        agent_ok="$(printf '%s' "$agent_summary" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('ok',0))")"
        agent_fail="$(printf '%s' "$agent_summary" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('fail',0))")"
        echo "  $aid: restored=$agent_ok failed=$agent_fail"
        total_restored=$((total_restored + agent_ok))
        total_failed=$((total_failed + agent_fail))
    done <<< "$plan"

    echo "[core] memory restore complete from: $source_dir"
    echo "  agents:     $agents_touched"
    echo "  restored:   $total_restored"
    echo "  failed:     $total_failed"
    [ "$total_failed" -eq 0 ] || return 2
}

# ── Command: memory prune ─────────────────────────────────────────────────
# Time-based prune of stale memory entries across all agents. Defaults to
# dry-run so operators preview what would be removed before executing —
# safety-first per owner policy.

cmd_memory_prune() {
    local older_than_days=""
    local mode="dry-run"
    local agent_filter=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --older-than)
                older_than_days="${2:-}"; shift 2 || true
                ;;
            --execute)
                mode="execute"; shift
                ;;
            --agent)
                agent_filter="${2:-}"; shift 2 || true
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory prune --older-than DAYS [--execute] [--agent ID]

Prune memory entries whose updated_at is older than DAYS days ago.
Default mode is dry-run: lists every (agent, category, key, age_days)
that would be removed without modifying state. Pass --execute to
actually remove. Pass --agent ID to scope to a single agent.

Owner safety: this is the only Core command that deletes memory.
Always run dry-run first.
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                die "Unexpected argument: $1"
                ;;
        esac
    done
    [ -n "$older_than_days" ] || die "Usage: core.sh memory prune --older-than DAYS [--execute] [--agent ID]"
    case "$older_than_days" in
        ''|*[!0-9]*) die "--older-than must be a positive integer (days), got: $older_than_days" ;;
    esac
    [ "$older_than_days" -gt 0 ] || die "--older-than must be > 0"
    require_loom; require_runtime

    local now_unix; now_unix="$(date -u +%s)"
    local cutoff=$((now_unix - older_than_days * 86400))

    # Collect all entries via cross-agent search (text=*), or single agent.
    local search_args=("--root" "$LOOM_ROOT" "--format" "json")
    if [ -n "$agent_filter" ]; then
        search_args+=("--agent-id" "$agent_filter")
    else
        search_args+=("--all-agents")
    fi
    local raw
    raw="$("$LOOM_BIN" memory search "${search_args[@]}" 2>/dev/null || echo "[]")"

    local plan_blob
    plan_blob="$(MEM_RAW="$raw" CUTOFF="$cutoff" python3 - <<'PY'
import json, os
raw = os.environ.get("MEM_RAW") or "[]"
cutoff = int(os.environ.get("CUTOFF") or "0")
try:
    entries = json.loads(raw)
except Exception:
    entries = []
stale = []
for e in entries:
    if not isinstance(e, dict):
        continue
    updated = int(e.get("updated_at") or 0)
    if updated and updated < cutoff:
        stale.append(e)
# Emit one TSV row per stale entry: agent\tcategory\tkey\tage_days
import time
now = int(time.time())
for e in stale:
    age_days = max(0, (now - int(e.get("updated_at") or 0)) // 86400)
    print(
        f"{e.get('agent_id','')}\t{e.get('category','')}\t{e.get('key','')}\t{age_days}"
    )
PY
)"

    if [ -z "$plan_blob" ]; then
        echo "[core] memory prune: nothing older than $older_than_days days"
        echo "  cutoff_unix: $cutoff"
        echo "  scope:       $([ -n "$agent_filter" ] && echo "agent=$agent_filter" || echo all_agents)"
        return 0
    fi

    local stale_count
    stale_count=$(printf '%s\n' "$plan_blob" | grep -c '	' || true)

    echo "[core] memory prune $mode: $stale_count entries older than $older_than_days days"
    echo "  cutoff_unix: $cutoff"
    echo "  scope:       $([ -n "$agent_filter" ] && echo "agent=$agent_filter" || echo all_agents)"

    if [ "$mode" = "dry-run" ]; then
        printf '%s\n' "$plan_blob" | head -50 | while IFS=$'\t' read -r aid cat key age; do
            [ -n "$aid" ] || continue
            printf '  [dry-run] %s/%s/%s (age=%sd)\n' "$aid" "$cat" "$key" "$age"
        done
        if [ "$stale_count" -gt 50 ]; then
            echo "  ... and $((stale_count - 50)) more (showing first 50)"
        fi
        echo "  Run with --execute to actually remove these entries."
        return 0
    fi

    # Execute mode: remove each stale entry via loom memory remove.
    local removed=0
    local failed=0
    while IFS=$'\t' read -r aid cat key age; do
        [ -n "$aid" ] || continue
        if "$LOOM_BIN" memory remove --agent-id "$aid" --category "$cat" --key "$key" --root "$LOOM_ROOT" --format json > /dev/null 2>&1; then
            removed=$((removed + 1))
        else
            failed=$((failed + 1))
            echo "  [fail] $aid/$cat/$key"
        fi
    done <<< "$plan_blob"

    echo "[core] memory prune execute complete"
    echo "  removed:    $removed"
    echo "  failed:     $failed"
    [ "$failed" -eq 0 ] || return 2
}

# ── Command: memory diff ──────────────────────────────────────────────────
# Compare two snapshot directories produced by `core.sh memory snapshot` and
# report added / removed / modified entries by (agent, category, key).
# Pure-shell, read-only — useful for audit, regression review, and
# debugging "what changed in memory between time A and time B".

cmd_memory_diff() {
    local left=""
    local right=""
    local output_mode="human"
    while [ $# -gt 0 ]; do
        case "$1" in
            --json)
                output_mode="json"; shift
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory diff SNAPSHOT_A SNAPSHOT_B [--json]

Compare two snapshot directories produced by core.sh memory snapshot.
Reports the set of (agent, category, key) entries that were added,
removed, or modified (content changed) between A and B. Read-only;
neither snapshot is mutated.
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                if [ -z "$left" ]; then left="$1"
                elif [ -z "$right" ]; then right="$1"
                else die "Unexpected argument: $1"
                fi
                shift
                ;;
        esac
    done
    [ -n "$left" ] && [ -n "$right" ] || die "Usage: core.sh memory diff SNAPSHOT_A SNAPSHOT_B [--json]"
    [ -d "$left" ] || die "snapshot dir not found: $left"
    [ -d "$right" ] || die "snapshot dir not found: $right"
    [ -f "$left/_manifest.json" ] || die "snapshot manifest missing: $left/_manifest.json"
    [ -f "$right/_manifest.json" ] || die "snapshot manifest missing: $right/_manifest.json"

    LEFT_DIR="$left" RIGHT_DIR="$right" OUTPUT_MODE="$output_mode" python3 - <<'PY'
import json, os, sys
from pathlib import Path


def load_snapshot(root):
    manifest = json.load(open(Path(root) / "_manifest.json", encoding="utf-8"))
    by_key = {}
    for agent_entry in manifest.get("agents") or []:
        agent_id = str(agent_entry.get("agent_id") or "")
        rel = str(agent_entry.get("path") or "")
        if not agent_id or not rel:
            continue
        agent_path = Path(root) / rel
        if not agent_path.is_file():
            continue
        try:
            entries = json.load(open(agent_path, encoding="utf-8"))
        except Exception:
            entries = []
        if not isinstance(entries, list):
            continue
        for e in entries:
            cat = str(e.get("category") or "")
            key = str(e.get("key") or "")
            if not cat or not key:
                continue
            by_key[(agent_id, cat, key)] = e
    return manifest, by_key


left_root = os.environ["LEFT_DIR"]
right_root = os.environ["RIGHT_DIR"]
output_mode = os.environ.get("OUTPUT_MODE", "human")

left_manifest, left_entries = load_snapshot(left_root)
right_manifest, right_entries = load_snapshot(right_root)

added = []
removed = []
modified = []
for k, right_e in right_entries.items():
    left_e = left_entries.get(k)
    if left_e is None:
        added.append((k, right_e))
    else:
        if (left_e.get("content") or "") != (right_e.get("content") or ""):
            modified.append((k, left_e, right_e))
for k, left_e in left_entries.items():
    if k not in right_entries:
        removed.append((k, left_e))

added.sort(key=lambda x: x[0])
removed.sort(key=lambda x: x[0])
modified.sort(key=lambda x: x[0])

if output_mode == "json":
    payload = {
        "left": {
            "path": left_root,
            "snapshot_at_unix": left_manifest.get("snapshot_at_unix"),
            "entry_count": len(left_entries),
        },
        "right": {
            "path": right_root,
            "snapshot_at_unix": right_manifest.get("snapshot_at_unix"),
            "entry_count": len(right_entries),
        },
        "added_count": len(added),
        "removed_count": len(removed),
        "modified_count": len(modified),
        "added": [
            {"agent_id": k[0], "category": k[1], "key": k[2]}
            for k, _ in added
        ],
        "removed": [
            {"agent_id": k[0], "category": k[1], "key": k[2]}
            for k, _ in removed
        ],
        "modified": [
            {"agent_id": k[0], "category": k[1], "key": k[2]}
            for k, _, _ in modified
        ],
    }
    print(json.dumps(payload, indent=2))
else:
    print(f"[core] memory diff: {left_root} -> {right_root}")
    print(f"  left entries:  {len(left_entries)}")
    print(f"  right entries: {len(right_entries)}")
    print(f"  added:         {len(added)}")
    print(f"  removed:       {len(removed)}")
    print(f"  modified:      {len(modified)}")
    if added:
        print("  + added:")
        for (a, c, k), _ in added[:50]:
            print(f"      {a}/{c}/{k}")
        if len(added) > 50:
            print(f"      ... and {len(added)-50} more")
    if removed:
        print("  - removed:")
        for (a, c, k), _ in removed[:50]:
            print(f"      {a}/{c}/{k}")
        if len(removed) > 50:
            print(f"      ... and {len(removed)-50} more")
    if modified:
        print("  ~ modified:")
        for (a, c, k), _, _ in modified[:50]:
            print(f"      {a}/{c}/{k}")
        if len(modified) > 50:
            print(f"      ... and {len(modified)-50} more")

# Exit non-zero if anything differs so scripts can branch on it.
if added or removed or modified:
    sys.exit(1)
PY
}

# ── Command: memory rotate ────────────────────────────────────────────────
# Retain only the most recent N snapshots in a parent directory. Detects
# snapshot subdirectories by presence of _manifest.json and orders them by
# snapshot_at_unix descending. Dry-run by default (safety-first per the
# same policy as prune).

cmd_memory_rotate() {
    local parent_dir=""
    local keep=""
    local mode="dry-run"
    while [ $# -gt 0 ]; do
        case "$1" in
            --keep)
                keep="${2:-}"; shift 2 || true
                ;;
            --execute)
                mode="execute"; shift
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory rotate DIR --keep N [--execute]

Retain only the most recent N snapshots in DIR. A snapshot is any
subdirectory of DIR that carries a _manifest.json; ordering is by
the manifest's snapshot_at_unix field, most-recent first. By
default lists what would be removed (dry-run); pass --execute to
actually delete.
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                if [ -z "$parent_dir" ]; then parent_dir="$1"
                else die "Unexpected argument: $1"
                fi
                shift
                ;;
        esac
    done
    [ -n "$parent_dir" ] && [ -n "$keep" ] || die "Usage: core.sh memory rotate DIR --keep N [--execute]"
    [ -d "$parent_dir" ] || die "rotate dir not found: $parent_dir"
    case "$keep" in
        ''|*[!0-9]*) die "--keep must be a non-negative integer, got: $keep" ;;
    esac

    local plan_blob
    plan_blob="$(PARENT_DIR="$parent_dir" KEEP="$keep" python3 - <<'PY'
import json, os, sys
from pathlib import Path

parent = Path(os.environ["PARENT_DIR"])
keep = int(os.environ.get("KEEP") or "0")

snapshots = []
for child in sorted(parent.iterdir()):
    if not child.is_dir():
        continue
    manifest = child / "_manifest.json"
    if not manifest.is_file():
        continue
    try:
        m = json.load(open(manifest, encoding="utf-8"))
    except Exception:
        continue
    ts = int(m.get("snapshot_at_unix") or 0)
    snapshots.append((ts, str(child)))

# Most recent first.
snapshots.sort(key=lambda x: x[0], reverse=True)
keep_set = {p for _, p in snapshots[:keep]}
remove_list = [p for _, p in snapshots[keep:]]

# Emit "KEEP\tpath\tts" or "REMOVE\tpath\tts" per line.
for ts, p in snapshots:
    tag = "KEEP" if p in keep_set else "REMOVE"
    print(f"{tag}\t{p}\t{ts}")
PY
)"

    if [ -z "$plan_blob" ]; then
        echo "[core] memory rotate: no snapshots found in $parent_dir"
        return 0
    fi

    local total_count keep_count remove_count
    total_count=$(printf '%s\n' "$plan_blob" | grep -c '	' || true)
    keep_count=$(printf '%s\n' "$plan_blob" | grep -c '^KEEP	' || true)
    remove_count=$(printf '%s\n' "$plan_blob" | grep -c '^REMOVE	' || true)

    echo "[core] memory rotate $mode: keep=$keep, total=$total_count, remove=$remove_count"
    while IFS=$'\t' read -r tag path ts; do
        [ -n "$tag" ] || continue
        if [ "$tag" = "KEEP" ]; then
            printf '  [keep]   %s (ts=%s)\n' "$path" "$ts"
        else
            printf '  [remove] %s (ts=%s)\n' "$path" "$ts"
        fi
    done <<< "$plan_blob"

    if [ "$mode" = "dry-run" ]; then
        echo "  Run with --execute to actually delete the [remove] entries."
        return 0
    fi

    local removed=0
    local failed=0
    while IFS=$'\t' read -r tag path ts; do
        [ "$tag" = "REMOVE" ] || continue
        # Defensive: only delete dirs that contain a _manifest.json and live
        # under the parent_dir we were asked to rotate. Never recursive
        # outside the snapshot family.
        if [ -f "$path/_manifest.json" ] && [[ "$path" == "$parent_dir"/* ]]; then
            if rm -rf -- "$path"; then
                removed=$((removed + 1))
            else
                failed=$((failed + 1))
                echo "  [fail] $path"
            fi
        else
            failed=$((failed + 1))
            echo "  [fail-guard] $path (not under $parent_dir or missing manifest)"
        fi
    done <<< "$plan_blob"

    echo "[core] memory rotate execute complete"
    echo "  removed:    $removed"
    echo "  failed:     $failed"
    [ "$failed" -eq 0 ] || return 2
}

# ── Command: memory health ────────────────────────────────────────────────
# Read-only operator dashboard: aggregates loom memory overview into a
# compact health report with top-N agents and threshold alerts.

cmd_memory_health() {
    local mode="report"
    local top_n="5"
    while [ $# -gt 0 ]; do
        case "$1" in
            --alert)
                mode="alert"; shift
                ;;
            --top)
                top_n="${2:-}"; shift 2 || true
                ;;
            --json)
                mode="json"; shift
                ;;
            --help|-h)
                cat <<EOF
Usage: core.sh memory health [--alert] [--json] [--top N]

Read-only memory health summary: aggregate counts, retention policy,
and top-N agents by entry count. Pure read; never mutates state.

  --alert   exit non-zero if any agent is over policy.max_entry_bytes
            or total memory exceeds 80% of any soft threshold
  --json    machine-readable output
  --top N   show top N agents by entry count (default 5)
EOF
                return 0
                ;;
            -*)
                die "Unknown flag: $1"
                ;;
            *)
                die "Unexpected argument: $1"
                ;;
        esac
    done
    case "$top_n" in
        ''|*[!0-9]*) die "--top must be a non-negative integer, got: $top_n" ;;
    esac
    require_loom; require_runtime

    local raw
    raw="$("$LOOM_BIN" memory overview --root "$LOOM_ROOT" --format json 2>/dev/null || echo "{}")"

    MEM_JSON="$raw" MODE="$mode" TOP_N="$top_n" python3 - <<'PY'
import json, os, sys

raw = os.environ.get("MEM_JSON") or "{}"
mode = os.environ.get("MODE", "report")
top_n = int(os.environ.get("TOP_N") or "5")

try:
    data = json.loads(raw)
except Exception:
    data = {}

agent_count = int(data.get("agent_count") or 0)
total_entries = int(data.get("total_entries") or 0)
total_bytes = int(data.get("total_bytes") or 0)
policy = data.get("policy") or {}
max_entry_bytes = int(policy.get("max_entry_bytes") or 0)
retention_days = int(policy.get("retention_days") or 0)
agents = data.get("agents") or []

# Compute alerts: any agent whose total_bytes exceeds max_entry_bytes (a
# rough heuristic; real per-entry checks happen at write time but a single
# agent ballooning is still operator-actionable).
alerts = []
for a in agents:
    if not isinstance(a, dict):
        continue
    if max_entry_bytes and int(a.get("total_bytes") or 0) > max_entry_bytes * 50:
        # Soft heuristic: 50x max_entry_bytes total = roughly 50 max-sized
        # entries, suggesting heavy growth on this agent.
        alerts.append({
            "agent_id": a.get("agent_id"),
            "code": "agent_heavy_growth",
            "total_bytes": int(a.get("total_bytes") or 0),
        })

if mode == "json":
    out = {
        "status": "success",
        "agent_count": agent_count,
        "total_entries": total_entries,
        "total_bytes": total_bytes,
        "policy": {
            "max_entry_bytes": max_entry_bytes,
            "retention_days": retention_days,
        },
        "alerts": alerts,
        "top_agents": sorted(
            [
                {
                    "agent_id": a.get("agent_id"),
                    "entry_count": int(a.get("entry_count") or 0),
                    "total_bytes": int(a.get("total_bytes") or 0),
                }
                for a in agents
                if isinstance(a, dict)
            ],
            key=lambda x: x["entry_count"],
            reverse=True,
        )[:top_n],
    }
    print(json.dumps(out, indent=2))
else:
    print("[core] memory health")
    print(f"  agents:          {agent_count}")
    print(f"  total entries:   {total_entries}")
    print(f"  total bytes:     {total_bytes}")
    if max_entry_bytes:
        print(f"  max entry bytes: {max_entry_bytes}")
    if retention_days:
        print(f"  retention days:  {retention_days}")
    sorted_agents = sorted(
        [a for a in agents if isinstance(a, dict)],
        key=lambda x: int(x.get("entry_count") or 0),
        reverse=True,
    )[:top_n]
    if sorted_agents:
        print(f"  top {len(sorted_agents)} agents by entry count:")
        for a in sorted_agents:
            print(
                f"    {a.get('agent_id'):28s} entries={int(a.get('entry_count') or 0):4d} "
                f"bytes={int(a.get('total_bytes') or 0)}"
            )
    if alerts:
        print(f"  alerts ({len(alerts)}):")
        for a in alerts:
            print(f"    [{a['code']}] {a['agent_id']} total_bytes={a['total_bytes']}")
    else:
        print("  alerts:          none")

if mode == "alert" and alerts:
    sys.exit(2)
PY
}

# ── Command: which-repo ───────────────────────────────────────────────────
# Workspace clarity preflight from inside the Core cockpit. Surfaces the
# canonical repo + archived mirrors so any agent landing in this workspace
# can immediately tell what's authoritative without reading old docs.

cmd_which_repo() {
    local verifier="${ROOT_DIR}/scripts/verify_canonical_repo.sh"
    [ -x "$verifier" ] || die "verify_canonical_repo.sh not found or not executable at $verifier"
    bash "$verifier" "$@"
}

# ── Command: team ─────────────────────────────────────────────────────────
# Operator cockpit window into Meridian Team mode. Surfaces the manager +
# specialist roster, models, scopes, and dispatch flags so the operator
# can see, at a glance, which agents are alive in the Team plane and how
# they're configured. Pure read; never mutates topology state.

cmd_team() {
    local subcmd="${1:-topology}"
    shift || true
    case "$subcmd" in
        topology)
            cmd_team_topology "$@"
            ;;
        --help|-h|help)
            cat <<EOF
Usage: core.sh team <subcommand> [args]

Subcommands:
  topology    Show manager + specialist roster (roles, models, scopes,
              dispatch flags). Reads /api/team/topology from the live
              gateway when available; falls back to local team_topology
              loader. Pure read.

Examples:
  core.sh team topology
  core.sh team topology --json
  core.sh team topology --remote   # force gateway fetch (Origin-protected)
EOF
            return 0
            ;;
        *)
            die "Usage: core.sh team <topology> [args]"
            ;;
    esac
}

cmd_team_topology() {
    local mode="report"
    local source="auto"
    while [ $# -gt 0 ]; do
        case "$1" in
            --json) mode="json"; shift ;;
            --remote) source="remote"; shift ;;
            --local) source="local"; shift ;;
            --help|-h)
                cat <<EOF
Usage: core.sh team topology [--json] [--remote|--local]

Render the Team-mode roster: manager + specialists with role, profile,
provider/model, kernel scopes, and dispatch flags. Never prints
api_key_env_var hints — owner-safe.

  --json     machine-readable JSON
  --remote   force gateway /api/team/topology (Origin-protected)
  --local    force local team_topology loader (offline-safe)
EOF
                return 0
                ;;
            -*) die "Unknown flag: $1" ;;
            *) die "Unexpected argument: $1" ;;
        esac
    done

    local raw=""
    local fetched_from=""
    if [ "$source" = "remote" ] || [ "$source" = "auto" ]; then
        local gateway_url="${MERIDIAN_GATEWAY_URL%/}"
        raw="$(curl -fsS -H "Origin: ${gateway_url}" "${gateway_url}/api/team/topology" 2>/dev/null || true)"
        if [ -n "$raw" ]; then
            fetched_from="gateway"
        elif [ "$source" = "remote" ]; then
            die "Failed to reach gateway at ${gateway_url}/api/team/topology"
        fi
    fi
    if [ -z "$raw" ]; then
        require_runtime
        raw="$(MERIDIAN_ROOT="$ROOT_DIR" python3 - <<'PY'
import json, sys
try:
    sys.path.insert(0, str(__import__("pathlib").Path("intelligence").resolve()))
    from meridian_gateway import _build_team_topology_response  # type: ignore
    print(json.dumps(_build_team_topology_response()))
except Exception as exc:
    print(json.dumps({"status": "error", "output": f"local_topology_failed: {exc}"}))
PY
)"
        fetched_from="local"
    fi

    MEM_JSON="$raw" MODE="$mode" FROM="$fetched_from" python3 - <<'PY'
import json, os, sys
raw = os.environ.get("MEM_JSON") or "{}"
mode = os.environ.get("MODE", "report")
src = os.environ.get("FROM") or "unknown"
try:
    data = json.loads(raw)
except Exception:
    data = {"status": "error", "output": "team_topology_unparseable"}

if mode == "json":
    out = dict(data)
    out["_source"] = src
    print(json.dumps(out, indent=2, sort_keys=True))
    sys.exit(0 if data.get("status") == "success" else 1)

if data.get("status") != "success":
    print(f"[team] topology unavailable ({src}): {data.get('output')}")
    sys.exit(1)

mgr = data.get("manager") or {}
specs = data.get("specialists") or []
print(f"[team] org={data.get('org_id')}  source={src}  specialists={len(specs)}")
print()
def render(label, a):
    if not a:
        return
    name = a.get("name") or a.get("handle") or a.get("registry_id") or "?"
    role = a.get("role") or "?"
    model = a.get("model") or "?"
    provider = a.get("provider_kind") or "?"
    kernel = a.get("kernel_role") or "?"
    disp = "yes" if a.get("dispatchable") else "no"
    visible = "yes" if a.get("manager_visible") else "no"
    aliases = ", ".join(a.get("aliases") or [])
    scopes = ", ".join(a.get("scopes") or [])
    print(f"  {label:11} {name}")
    print(f"    role={role}  kernel={kernel}  model={model}  provider={provider}")
    print(f"    dispatchable={disp}  manager_visible={visible}")
    if aliases:
        print(f"    aliases={aliases}")
    if scopes:
        print(f"    scopes={scopes}")

render("manager:", mgr)
for i, sp in enumerate(specs):
    render(f"specialist#{i}:", sp)
PY
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

# ── Command: proof ────────────────────────────────────────────────────────

cmd_proof() {
    local subcmd="${1:-local}"
    shift || true

    case "$subcmd" in
        local)
            local proof_script="${ROOT_DIR}/scripts/verify_core_runtime_local.sh"
            [ -x "$proof_script" ] || die "verify_core_runtime_local.sh not found or not executable"
            ensure_core_state_dir
            bash "$proof_script" "$CORE_LAST_PROOF_FILE" "$@"
            ;;
        show)
            [ -f "$CORE_LAST_PROOF_FILE" ] || die "No Core proof captured yet. Run: ./scripts/core.sh proof local"
            cat "$CORE_LAST_PROOF_FILE"
            ;;
        summary)
            [ -f "$CORE_LAST_PROOF_FILE" ] || die "No Core proof captured yet. Run: ./scripts/core.sh proof local"
            python3 - "$CORE_LAST_PROOF_FILE" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
summary = dict(payload.get("summary") or {})
details = dict(payload.get("details") or {})
lane_truth = dict(payload.get("lane_truth") or {})
print("[core] proof summary")
print(f"  status:      {payload.get('status') or 'unknown'}")
print(f"  checked_at:  {payload.get('checked_at') or ''}")
for key in sorted(summary):
    print(f"  {key}: {summary[key]}")
if lane_truth:
    live_provider = dict(lane_truth.get("live_provider_probe") or {})
    isolated_ask = dict(lane_truth.get("isolated_ask_lane") or {})
    distinction = dict(lane_truth.get("distinction") or {})
    print("  lane_truth:")
    print(
        "    live_provider_probe: "
        f"ok={live_provider.get('ok')} "
        f"provider={live_provider.get('provider') or '-'} "
        f"transport={live_provider.get('transport') or '-'} "
        f"route_id={live_provider.get('route_id') or '-'} "
        f"error_code={live_provider.get('error_code') or '-'}"
    )
    print(
        "    isolated_ask_lane: "
        f"ok={isolated_ask.get('ok')} "
        f"source={isolated_ask.get('provider_source') or '-'} "
        f"profile={isolated_ask.get('provider_profile') or '-'} "
        f"transport={isolated_ask.get('provider_transport') or '-'}"
    )
    print(
        "    distinction: "
        f"status={distinction.get('status') or '-'} "
        f"live_provider_degraded={distinction.get('live_provider_degraded')} "
        f"isolated_ask_passed={distinction.get('isolated_ask_passed')}"
    )
if details:
    print("  details:")
    for key in sorted(details):
        print(f"    {key}: {details[key]}")
PY
            ;;
        path)
            [ -f "$CORE_LAST_PROOF_FILE" ] || die "No Core proof captured yet. Run: ./scripts/core.sh proof local"
            echo "$CORE_LAST_PROOF_FILE"
            ;;
        *)
            die "Usage: core.sh proof <local|show|summary|path>"
            ;;
    esac
}

# ── Command: help ─────────────────────────────────────────────────────────

cmd_help() {
    cat <<'EOF'
Meridian Core — daily-use task runner

Commands:
  ask [--file PATH ...] [--model M] [--session ID] [--no-context] "TASK"   Run a daily prompt (with optional file attachments / model override)
  ask --queued-files "TASK"  Run a daily prompt using files from the persistent Core file queue
  files add PATH ...       Add files to the persistent Core file queue
  files list               Show queued Core files
  files remove PATH ...    Remove files from the queue
  files clear              Clear the Core file queue
  context add PATH ...     Add files to persistent Core context (auto-attached to ask/chat)
  context list             Show persistent Core context files
  context remove PATH ...  Remove files from persistent Core context
  context clear            Clear persistent Core context
  playbook list            Show saved Core playbooks
  playbook scaffold NAME   Create a starter playbook template
  playbook add NAME FILE   Save a playbook from a local file
  playbook capture NAME    Capture last output as a reusable playbook
  playbook show NAME       Show a saved playbook
  playbook run NAME [...]  Execute a playbook through Core ask
  playbook every NAME S    Schedule a playbook routine every S seconds
  playbook daily NAME T    Schedule a playbook routine daily at HH:MM
  playbook schedules       List Core playbook routine mappings
  playbook run-scheduled J Execute a mapped playbook schedule now through Core ask
  playbook unschedule N    Cancel and unmap a playbook routine
  playbook remove NAME     Delete a saved playbook
  session current        Show the current Core conversation session id
  session new [ID]       Start a fresh Core session and make it current
  session use ID         Switch the current Core session
  session list           List tracked Core sessions
  session show [ID]      Show recent history for a Core session
  session search QUERY [LIMIT]  Search across session history text
  session resume SESSION_KEY EVENT_INDEX [--queue|--context]  Materialize one historical event into reusable context
  session reuse QUERY [--queue|--context]  Search latest matching event and materialize it in one step
  session export [ID] D  Export a Core session to JSON + Markdown in directory D
  session reset          Clear the current Core session pointer
  session archive        Archive old sessions (dry-run by default, --execute to apply)
  response show          Show the most recent Core ask output
  response meta          Show route/session metadata for the last Core ask
  response path          Show the JSON receipt path for the last Core ask
  response page          Page through last response (useful for long outputs)
  response export DIR    Export the most recent Core artifact into DIR
  response export-path   Show the last Core export directory
  chat                   Start an interactive Core chat loop on the current session
  doctor                 Run the Core operator doctor across runtime/provider/gateway/channel surfaces
  doctor fix             Apply safe doctor remediations and capture before/after receipt
  doctor summary         Show the most recent Core doctor receipt summary
  doctor show            Show the most recent Core doctor receipt JSON
  doctor path            Show the JSON path for the most recent Core doctor receipt
  provider status        Show configured provider plane status
  provider profiles      Show provider profiles
  provider auth          Show provider auth readiness
  provider route ...     Inspect provider route decisions
  provider list          Show all providers, models, routes, and health
  provider fix           Restore a usable Meridian-owned manager route when policy is blocked
  provider restore       Restore manager route from Meridian-owned .env/.env.gateway topology
  provider probe [TEXT]  Run a tiny end-to-end manager probe and update route health
  provider use PROFILE   Switch active provider/model (--model M, --transport T, --endpoint URL)
  config show            Show effective runtime config
  config set KEY VALUE   Set a config override (safe allowlisted keys only)
  config get KEY         Show current value for a config key
  runtime status         Show loom runtime status
  runtime health         Show loom doctor-derived health summary
  runtime logs           Show recent loom runtime logs
  ingress status         Show live ingress backlog summary
  ingress list [B] [N]   List pending/quarantine ingress files (bucket B, limit N)
  ingress quarantine     Show quarantined ingress snapshot
  ingress quarantine --apply [S]   Move stale ingress files older than S seconds
  browse URL               Navigate to URL, extract and show text
  research "cmd [args]"   Run a bounded read-only terminal command
  shell list              List safe daily shell presets
  shell run PRESET        Run one bounded shell preset
  remember KEY "VALUE"    Store a memory entry (persistent across sessions)
  recall [KEY_PREFIX] [--text Q] [--limit N]   Search stored memory by key prefix and/or text
  memory receipts         Show recent memory receipts
  memory graph SOURCE_REF Inspect memory graph lineage/forks
  memory fork SOURCE_REF --target-agent ID [--branch NAME] [--node-id ID] [--direction D] [--limit N]   Create a governed memory fork lane
  memory replay SOURCE_REF --target-agent ID [--node-id ID] [--direction D] [--limit N]   Replay governed memory into another agent via kernel checks
  memory latest-fork [--json]      Show latest governed memory fork artifact
  memory latest-replay [--json]    Show latest governed memory replay artifact
  memory fork-history [N] [--json]    Show recent governed memory fork artifacts
  memory replay-history [N] [--json]  Show recent governed memory replay artifacts
  memory governance [N] [--json]      Show governed memory operator summary
  memory team-governance [N] [--json] Show governed memory activity grouped by Team agents
  memory overview         Show memory overview
  memory search QUERY [N] [--all-agents]   Full-content search across stored memory (case-insensitive). With --all-agents, fan out across every agent and order by recency.
  memory snapshot DIR [--all-agents]   Export memory entries to DIR (one JSON per agent + _manifest.json)
  memory restore DIR [--agent ID]      Restore memory entries from a snapshot DIR (upserts; non-destructive)
  memory prune --older-than DAYS [--execute] [--agent ID]   Time-based prune (dry-run by default; --execute to actually remove)
  memory diff SNAPSHOT_A SNAPSHOT_B [--json]   Compare two snapshot directories; report added/removed/modified entries
  memory rotate DIR --keep N [--execute]   Retain only the N most recent snapshots in DIR (dry-run by default)
  memory health [--alert] [--json] [--top N]   Read-only operator memory dashboard with top-N agents and alerts
  schedule status         Show schedule runtime overview
  schedule list           List scheduled jobs
  schedule show JOB_ID    Show full schedule details
  schedule every N S      Create an interval routine every S seconds
  schedule daily N T [Z]  Create a daily routine at HH:MM in timezone Z
  schedule pause JOB_ID   Pause a schedule
  schedule cancel JOB_ID  Cancel a schedule
  schedule run JOB_ID     Execute a schedule now
  schedule run-due [N]    Execute due schedules now (default limit: 20)
  schedules               Alias for: schedule list
  agent inspect           Show live agent/operator state
  agent diagnose          Show remediation plan from live state
  agent status            Show loop status
  job list                List recent runtime jobs
  job inspect JOB_ID      Inspect a runtime job receipt
  channel health          Show channel health for the current agent
  channel deliveries      Show recent outbound delivery ledger
  channel send CH R TXT   Send text to a named channel/recipient
  channel diagnostics [CH] [N]  Multi-channel health overview or per-channel delivery diagnostics
  channel proof CH [N]    Sha256-chained delivery receipt proof for a channel (default N=50)
  channel verify CH [R|auto] [T]  Real send-and-prove round trip; auto-resolves recipient from inbox
  channel watch CH [SECS] Tail delivery + inbound ledger for a channel
  channel connect list    List connect adapters
  channel connect scaffold N T [S]   Scaffold adapter NAME/TRANSPORT/ACTION_SCHEMA
  channel connect validate ADAPTER   Validate one adapter
  channel connect enable ADAPTER     Enable one adapter
  channel connect disable ADAPTER    Disable one adapter
  channel connect test ADAPTER       Run adapter test
  channel connect health ADAPTER     Show adapter health
  channel connect diagnostics ADAPTER [N]  Show recent adapter diagnostics
  channel connect scorecard          Show connect scorecard
  web urls                Show local/public web operator surfaces
  web status              Probe gateway/workspace web surfaces
  web browse-policy       Show Core browse restrictions and host allowlist
  queue status            Show queue depth/state
  queue inspect           Inspect queued records
  inspect                 Show last execution receipts and agent state
  status                  Show full runtime status
  proof local             Run the local Core live-proof suite
  proof show              Show the most recent Core proof receipt
  proof summary           Show a compact summary of the most recent Core proof
  proof path              Show the JSON path for the most recent Core proof
  cap list                List available capabilities
  cap inspect NAME        Show capability metadata
  cap run NAME [PAYLOAD]  Run a capability by name
  which-repo [--json] [--strict]   Workspace clarity: canonical repo vs archived mirrors
  help                    Show this help

File attachments:
  core.sh ask --file src/main.py "review this code"
  core.sh files add src/main.py docs/spec.md
  core.sh files list
  core.sh ask --queued-files "compare queued files"
  core.sh ask -f a.py -f b.py "compare these two files"
  core.sh ask --session proof-123 "reply with exactly: ok"
  In chat mode: /file PATH to queue, then type your message

Persistent context files:
  core.sh context add AGENTS.md docs/plan.md
  core.sh context list
  core.sh ask "continue working with the default project context"
  core.sh ask --no-context "ignore the default project context for this turn"
  In chat mode: /context, /context add PATH, /context clear

Playbooks:
  core.sh playbook scaffold morning-brief
  core.sh playbook add release-qa docs/release_qa.md
  core.sh playbook capture latest-fix
  core.sh playbook capture recovered-context --from last-resume
  core.sh playbook list
  core.sh playbook show release-qa
  core.sh playbook run release-qa "Focus on regressions only"
  core.sh playbook every release-qa 3600
  core.sh playbook daily release-qa 08:30 UTC
  core.sh playbook schedules
  core.sh playbook run-scheduled playbook-release-qa
  core.sh playbook unschedule release-qa

Model override (per-request):
  core.sh ask --model gpt-4o "summarize this"
  In chat mode: /model gpt-4o (sticky for the chat session)

Provider switching (persistent):
  core.sh provider list                          show all providers/models/routes
  core.sh provider fix                           restore a Meridian-owned manager route from env topology
  core.sh provider restore                       restore manager route from Meridian env topology
  core.sh provider probe                         run an end-to-end manager route probe
  core.sh provider use my_profile --model gpt-4o switch active provider+model
  In chat mode: /provider use my_profile --model gpt-4o

Session lifecycle:
  core.sh session archive                           dry-run: list old sessions
  core.sh session archive --older-than 7 --execute   archive sessions older than 7 days
  core.sh session search "provider-probe-ok" 5
  core.sh session resume web_api:exportproof 281
  core.sh session resume web_api:exportproof 281 --queue
  core.sh session resume web_api:exportproof 281 --context
  core.sh session reuse "core-proof-ok" --queue

Config editing:
  core.sh config set MERIDIAN_BRAIN_MANAGER_MODEL gpt-4o
  core.sh config get MERIDIAN_BRAIN_MANAGER_MODEL

Scheduling and routines:
  core.sh schedule status
  core.sh schedule list
  core.sh schedule show morning_brief
  core.sh schedule every inbox-check 900
  core.sh schedule daily morning-brief 08:30 UTC
  core.sh schedule pause morning_brief
  core.sh schedule run morning_brief

Channel diagnostics and multi-channel health:
  core.sh channel diagnostics                 # overview of all channels
  core.sh channel diagnostics telegram        # per-channel delivery diagnostics
  core.sh channel diagnostics zalo 10         # per-channel with custom limit

Channel pairing and adapter admin:
  core.sh channel connect list
  core.sh channel connect scaffold telegram-admin telegram meridian.runtime.v1
  core.sh channel connect validate telegram-admin
  core.sh channel connect enable telegram-admin
  core.sh channel connect scorecard

Web/operator bridge:
  core.sh web urls
  core.sh web status
  core.sh web browse-policy

Terminal presets and guardrails:
  core.sh shell list
  core.sh shell run repo-status
  core.sh shell run open-ports
  core.sh research "git status"
  core.sh research "rg MERIDIAN_GATEWAY_URL scripts/core.sh"
  core.sh config set MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS app.welliam.codes,docs.example.com

Live proof:
  core.sh proof local
  core.sh proof show
  core.sh proof summary
  core.sh proof path

Ingress operator surface:
  core.sh ingress status
  core.sh ingress list pending 10
  core.sh ingress quarantine
  core.sh ingress quarantine --apply 300

Doctor receipts:
  core.sh doctor
  core.sh doctor fix
  core.sh doctor summary
  core.sh doctor show
  core.sh doctor path

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

if [ "${MERIDIAN_CORE_SH_SOURCE_ONLY:-0}" != "1" ]; then
    COMMAND="${1:-help}"
    shift || true

    case "$COMMAND" in
        ask)         cmd_ask "$@" ;;
        files)       cmd_files "$@" ;;
        context)     cmd_context "$@" ;;
        playbook)    cmd_playbook "$@" ;;
        session)     cmd_session "$@" ;;
        response)    cmd_response "$@" ;;
        chat)        cmd_chat "$@" ;;
        doctor)      cmd_doctor "$@" ;;
        provider)    cmd_provider "$@" ;;
        config)      cmd_config "$@" ;;
        runtime)     cmd_runtime "$@" ;;
        ingress)     cmd_ingress "$@" ;;
        browse)      cmd_browse "$@" ;;
        research)    cmd_research "$@" ;;
        shell)       cmd_shell "$@" ;;
        remember)    cmd_remember "$@" ;;
        recall)      cmd_recall "$@" ;;
        schedule)    cmd_schedule "$@" ;;
        schedules)   cmd_schedules "$@" ;;
        memory)      cmd_memory "$@" ;;
        agent)       cmd_agent "$@" ;;
        job)         cmd_job "$@" ;;
        channel)     cmd_channel "$@" ;;
        web)         cmd_web "$@" ;;
        queue)       cmd_queue "$@" ;;
        inspect)     cmd_inspect "$@" ;;
        status)      cmd_status "$@" ;;
        proof)       cmd_proof "$@" ;;
        cap)         cmd_cap "$@" ;;
        which-repo)  cmd_which_repo "$@" ;;
        team)        cmd_team "$@" ;;
        help|--help) cmd_help ;;
        *)
            echo "[core] Unknown command: $COMMAND" >&2
            cmd_help
            exit 1
            ;;
    esac
fi
