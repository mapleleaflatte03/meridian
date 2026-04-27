#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_PATH="${1:-}"
if [ -n "$OUT_PATH" ]; then
  shift || true
fi

echo "[verify-core] checking Core web/operator bridge"
./scripts/core.sh web status >/tmp/verify-core-web-status.txt
cat /tmp/verify-core-web-status.txt

echo
echo "[verify-core] checking schedule cockpit"
./scripts/core.sh schedule status >/tmp/verify-core-schedule-status.txt
cat /tmp/verify-core-schedule-status.txt

echo
echo "[verify-core] checking doctor surface"
./scripts/core.sh doctor fix >/tmp/verify-core-doctor.txt
tail -n 20 /tmp/verify-core-doctor.txt
./scripts/core.sh doctor summary >/tmp/verify-core-doctor-summary.txt
cat /tmp/verify-core-doctor-summary.txt

echo
echo "[verify-core] checking provider plane"
./scripts/core.sh provider list >/tmp/verify-core-provider-list.txt
head -n 80 /tmp/verify-core-provider-list.txt

echo
echo "[verify-core] checking config inspect"
./scripts/core.sh config get MERIDIAN_GATEWAY_URL >/tmp/verify-core-config-get.txt
cat /tmp/verify-core-config-get.txt

echo
echo "[verify-core] checking provider restore in isolated env root"
rm -rf /tmp/core-proof-local-env /tmp/core-proof-restore-kernel
mkdir -p /tmp/core-proof-local-env /tmp/core-proof-restore-kernel/economy
cat >/tmp/core-proof-restore-server.py <<'PY'
#!/usr/bin/env python3
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {}
        model = payload.get("model") or "mock-model"
        response = {
            "id": "chatcmpl-core-proof",
            "object": "chat.completion",
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "provider-probe-ok"}, "finish_reason": "stop"}],
        }
        data = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        return

HTTPServer(("127.0.0.1", 18777), Handler).serve_forever()
PY
python3 /tmp/core-proof-restore-server.py >/tmp/core-proof-restore-server.log 2>&1 &
PROVIDER_RESTORE_SERVER_PID=$!
cleanup_provider_restore_server() {
  if [ -n "${PROVIDER_RESTORE_SERVER_PID:-}" ]; then
    kill "${PROVIDER_RESTORE_SERVER_PID}" >/dev/null 2>&1 || true
    wait "${PROVIDER_RESTORE_SERVER_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup_provider_restore_server EXIT
cat >/tmp/core-proof-local-env/.env <<'EOF'
export MERIDIAN_MANAGER_MODEL=grok-4-1-fast-reasoning
export MERIDIAN_MANAGER_XAI_BASE_URL=http://127.0.0.1:18777/v1/chat/completions
export MERIDIAN_MANAGER_XAI_API_KEY_1=core-proof-key
EOF
cat >/tmp/core-proof-local-env/.env.gateway <<'EOF'
export MERIDIAN_BRAIN_MANAGER_ENDPOINT=http://127.0.0.1:18777/v1/chat/completions
export MERIDIAN_BRAIN_MANAGER_MODEL=grok-4-1-fast-reasoning
export MERIDIAN_BRAIN_MANAGER_AUTH_ENV=MERIDIAN_MANAGER_XAI_API_KEY_1
EOF
env \
  MERIDIAN_LOCAL_ENV_DIR=/tmp/core-proof-local-env \
  MERIDIAN_KERNEL_ROOT=/tmp/core-proof-restore-kernel \
  ./scripts/core.sh provider fix >/tmp/verify-core-provider-restore.txt
cat /tmp/verify-core-provider-restore.txt
env \
  MERIDIAN_LOCAL_ENV_DIR=/tmp/core-proof-local-env \
  MERIDIAN_KERNEL_ROOT=/tmp/core-proof-restore-kernel \
  ./scripts/core.sh provider probe >/tmp/verify-core-provider-restore-probe.txt
cat /tmp/verify-core-provider-restore-probe.txt
env \
  MERIDIAN_LOCAL_ENV_DIR=/tmp/core-proof-local-env \
  MERIDIAN_KERNEL_ROOT=/tmp/core-proof-restore-kernel \
  ./scripts/core.sh provider list >/tmp/verify-core-provider-restore-list.txt
head -n 80 /tmp/verify-core-provider-restore-list.txt

echo
echo "[verify-core] checking provider mutation in isolated kernel root"
rm -rf /tmp/core-proof-kernel
mkdir -p /tmp/core-proof-kernel/economy
env \
  MERIDIAN_KERNEL_ROOT=/tmp/core-proof-kernel \
  MERIDIAN_BRAIN_MANAGER_CLI_BIN=/usr/bin/echo \
  MERIDIAN_BRAIN_MANAGER_CLI_HOME=/tmp \
  ./scripts/core.sh provider use core_proof_provider --model core-proof-model --transport cli_session \
  >/tmp/verify-core-provider-mutation-switch.txt
cat /tmp/verify-core-provider-mutation-switch.txt
env \
  MERIDIAN_KERNEL_ROOT=/tmp/core-proof-kernel \
  ./scripts/core.sh provider list >/tmp/verify-core-provider-mutation-list.txt
head -n 80 /tmp/verify-core-provider-mutation-list.txt

echo
echo "[verify-core] checking config mutation in isolated loom root"
rm -rf /tmp/core-proof-loom
mkdir -p /tmp/core-proof-loom
env \
  MERIDIAN_LOOM_ROOT=/tmp/core-proof-loom \
  ./scripts/core.sh config set MERIDIAN_GATEWAY_URL http://127.0.0.1:9999 \
  >/tmp/verify-core-config-mutation-set.txt
cat /tmp/verify-core-config-mutation-set.txt
env \
  MERIDIAN_LOOM_ROOT=/tmp/core-proof-loom \
  ./scripts/core.sh config get MERIDIAN_GATEWAY_URL >/tmp/verify-core-config-mutation-get.txt
cat /tmp/verify-core-config-mutation-get.txt

echo
echo "[verify-core] checking channel connect cockpit"
./scripts/core.sh channel connect list >/tmp/verify-core-channel-connect.txt
cat /tmp/verify-core-channel-connect.txt

echo
echo "[verify-core] checking multi-channel diagnostics (file-based)"
./scripts/core.sh channel diagnostics >/tmp/verify-core-channel-diagnostics.txt 2>&1 || true
cat /tmp/verify-core-channel-diagnostics.txt

echo
echo "[verify-core] checking per-channel diagnostics for telegram (file-based)"
./scripts/core.sh channel diagnostics telegram 5 >/tmp/verify-core-channel-diagnostics-telegram.txt 2>&1 || true
cat /tmp/verify-core-channel-diagnostics-telegram.txt

echo
echo "[verify-core] checking shell presets"
./scripts/core.sh shell list >/tmp/verify-core-shell-list.txt
cat /tmp/verify-core-shell-list.txt

echo
echo "[verify-core] checking shell preset execution"
./scripts/core.sh shell run repo-status >/tmp/verify-core-shell-run.txt
head -n 40 /tmp/verify-core-shell-run.txt

echo
echo "[verify-core] checking research guardrails"
if ./scripts/core.sh research "git reset --hard" >/tmp/verify-core-guardrail.txt 2>&1; then
  echo "[verify-core] ERROR: destructive research command was not blocked" >&2
  exit 1
fi
cat /tmp/verify-core-guardrail.txt

echo
echo "[verify-core] checking browse policy"
./scripts/core.sh web browse-policy >/tmp/verify-core-browse-policy.txt
cat /tmp/verify-core-browse-policy.txt

echo
echo "[verify-core] checking persistent context files"
./scripts/core.sh context clear >/tmp/verify-core-context-clear-before.txt
mkdir -p /tmp/core-proof-context
printf 'project-context-proof\n' >/tmp/core-proof-context/context.txt
./scripts/core.sh context add /tmp/core-proof-context/context.txt >/tmp/verify-core-context-add.txt
cat /tmp/verify-core-context-add.txt
./scripts/core.sh context list >/tmp/verify-core-context-list.txt
cat /tmp/verify-core-context-list.txt
./scripts/core.sh ask "Reply with exactly: context-proof-ok" >/tmp/verify-core-context-ask.txt
cat /tmp/verify-core-context-ask.txt
grep -q "context-proof-ok" /tmp/verify-core-context-ask.txt
./scripts/core.sh ask --no-context "Reply with exactly: no-context-proof-ok" >/tmp/verify-core-context-noctx-ask.txt
cat /tmp/verify-core-context-noctx-ask.txt
grep -q "no-context-proof-ok" /tmp/verify-core-context-noctx-ask.txt
./scripts/core.sh context clear >/tmp/verify-core-context-clear-after.txt
cat /tmp/verify-core-context-clear-after.txt

echo
echo "[verify-core] checking playbook surface"
rm -rf runtime/default/state/core_cli/playbooks
rm -f runtime/default/state/core_cli/playbook_schedules.json
mkdir -p /tmp/core-proof-playbooks
cat >/tmp/core-proof-playbooks/release-qa.md <<'EOF'
# Proof Playbook

## Goal
Return exactly: playbook-proof-ok
EOF
./scripts/core.sh playbook scaffold morning-brief >/tmp/verify-core-playbook-scaffold.txt
cat /tmp/verify-core-playbook-scaffold.txt
./scripts/core.sh playbook add release-qa /tmp/core-proof-playbooks/release-qa.md >/tmp/verify-core-playbook-add.txt
cat /tmp/verify-core-playbook-add.txt
./scripts/core.sh playbook list >/tmp/verify-core-playbook-list.txt
cat /tmp/verify-core-playbook-list.txt
./scripts/core.sh playbook show release-qa >/tmp/verify-core-playbook-show.txt
cat /tmp/verify-core-playbook-show.txt
./scripts/core.sh playbook run release-qa >/tmp/verify-core-playbook-run.txt
cat /tmp/verify-core-playbook-run.txt
grep -q "playbook-proof-ok" /tmp/verify-core-playbook-run.txt
./scripts/core.sh playbook capture captured-proof >/tmp/verify-core-playbook-capture.txt
cat /tmp/verify-core-playbook-capture.txt
./scripts/core.sh playbook show captured-proof >/tmp/verify-core-playbook-captured-show.txt
cat /tmp/verify-core-playbook-captured-show.txt
grep -q "playbook-proof-ok" /tmp/verify-core-playbook-captured-show.txt
./scripts/core.sh playbook every release-qa 3600 >/tmp/verify-core-playbook-every.txt
cat /tmp/verify-core-playbook-every.txt
./scripts/core.sh playbook schedules >/tmp/verify-core-playbook-schedules.txt
cat /tmp/verify-core-playbook-schedules.txt
grep -q "playbook:release-qa" /tmp/verify-core-playbook-schedules.txt
./scripts/core.sh playbook run-scheduled playbook-release-qa >/tmp/verify-core-playbook-run-scheduled.txt
cat /tmp/verify-core-playbook-run-scheduled.txt
grep -q "playbook-proof-ok" /tmp/verify-core-playbook-run-scheduled.txt
./scripts/core.sh playbook unschedule release-qa >/tmp/verify-core-playbook-unschedule.txt
cat /tmp/verify-core-playbook-unschedule.txt

echo
echo "[verify-core] checking persistent file queue"
./scripts/core.sh files clear >/tmp/verify-core-files-clear.txt
mkdir -p /tmp/core-proof-files
printf 'queue-a\n' >/tmp/core-proof-files/a.txt
printf 'queue-b\n' >/tmp/core-proof-files/b.txt
./scripts/core.sh files add /tmp/core-proof-files/a.txt /tmp/core-proof-files/b.txt >/tmp/verify-core-files-add.txt
cat /tmp/verify-core-files-add.txt
./scripts/core.sh files list >/tmp/verify-core-files-list.txt
cat /tmp/verify-core-files-list.txt
./scripts/core.sh ask --queued-files "Reply with exactly: queued-proof-ok" >/tmp/verify-core-files-ask.txt
cat /tmp/verify-core-files-ask.txt
grep -q "queued-proof-ok" /tmp/verify-core-files-ask.txt
./scripts/core.sh files clear >/tmp/verify-core-files-clear-after.txt
cat /tmp/verify-core-files-clear-after.txt

echo
echo "[verify-core] checking Core ask"
./scripts/core.sh ask "Reply with exactly: core-proof-ok" >/tmp/verify-core-ask.txt
cat /tmp/verify-core-ask.txt
grep -q "core-proof-ok" /tmp/verify-core-ask.txt

echo
echo "[verify-core] checking attachment flow"
mkdir -p /tmp/core-proof-input
printf 'print("proof")\n' >/tmp/core-proof-input/sample.py
./scripts/core.sh ask --file /tmp/core-proof-input/sample.py "Reply with exactly: attach-proof-ok" >/tmp/verify-core-attach.txt
cat /tmp/verify-core-attach.txt
grep -q "attach-proof-ok" /tmp/verify-core-attach.txt

echo
echo "[verify-core] checking artifact export"
./scripts/core.sh ask $'Reply with exactly this markdown and nothing else:\n#### `app.py`\n```python\nprint("core-export-ok")\n```' >/tmp/verify-core-artifact-ask.txt
cat /tmp/verify-core-artifact-ask.txt
grep -q "core-export-ok" /tmp/verify-core-artifact-ask.txt
rm -rf /tmp/core-proof-export
./scripts/core.sh response export /tmp/core-proof-export >/tmp/verify-core-export.txt
cat /tmp/verify-core-export.txt
test -f /tmp/core-proof-export/app.py
grep -q "core-export-ok" /tmp/core-proof-export/app.py

echo
echo "[verify-core] checking session export"
rm -rf /tmp/core-proof-session-export
./scripts/core.sh session export exportproof /tmp/core-proof-session-export >/tmp/verify-core-session-export.txt
cat /tmp/verify-core-session-export.txt
test -f /tmp/core-proof-session-export/session.json
test -f /tmp/core-proof-session-export/session.md

echo
echo "[verify-core] checking session archive dry-run"
./scripts/core.sh session archive >/tmp/verify-core-session-archive.txt
cat /tmp/verify-core-session-archive.txt

echo
echo "[verify-core] checking session resume bridge"
./scripts/core.sh files clear >/tmp/verify-core-session-resume-clear-before.txt
./scripts/core.sh context clear >/tmp/verify-core-session-resume-context-clear-before.txt
./scripts/core.sh session resume web_api:exportproof 281 --queue >/tmp/verify-core-session-resume.txt
cat /tmp/verify-core-session-resume.txt
test -f runtime/default/state/core_cli/last_resume.txt
grep -q "Updated governed memory recall outcomes" runtime/default/state/core_cli/last_resume.txt
./scripts/core.sh files list >/tmp/verify-core-session-resume-files.txt
cat /tmp/verify-core-session-resume-files.txt
./scripts/core.sh session resume web_api:exportproof 281 --context >/tmp/verify-core-session-resume-context.txt
cat /tmp/verify-core-session-resume-context.txt
./scripts/core.sh context list >/tmp/verify-core-session-resume-context-files.txt
cat /tmp/verify-core-session-resume-context-files.txt
./scripts/core.sh files clear >/tmp/verify-core-session-resume-clear-after.txt
./scripts/core.sh context clear >/tmp/verify-core-session-resume-context-clear-after.txt

echo
echo "[verify-core] checking session reuse bridge"
./scripts/core.sh files clear >/tmp/verify-core-session-reuse-clear-before.txt
./scripts/core.sh context clear >/tmp/verify-core-session-reuse-context-clear-before.txt
./scripts/core.sh session reuse "core-proof-ok" --queue >/tmp/verify-core-session-reuse.txt
cat /tmp/verify-core-session-reuse.txt
test -f runtime/default/state/core_cli/last_resume.txt
grep -q "reuse_query" runtime/default/state/core_cli/last_resume.txt
grep -q "core-proof-ok" runtime/default/state/core_cli/last_resume.txt
./scripts/core.sh files list >/tmp/verify-core-session-reuse-files.txt
cat /tmp/verify-core-session-reuse-files.txt
./scripts/core.sh session reuse "core-proof-ok" --context >/tmp/verify-core-session-reuse-context.txt
cat /tmp/verify-core-session-reuse-context.txt
./scripts/core.sh context list >/tmp/verify-core-session-reuse-context-files.txt
cat /tmp/verify-core-session-reuse-context-files.txt
./scripts/core.sh files clear >/tmp/verify-core-session-reuse-clear-after.txt
./scripts/core.sh context clear >/tmp/verify-core-session-reuse-context-clear-after.txt

if [ -n "$OUT_PATH" ]; then
  python3 - "$OUT_PATH" \
    /tmp/verify-core-web-status.txt \
    /tmp/verify-core-schedule-status.txt \
    /tmp/verify-core-doctor.txt \
    /tmp/verify-core-doctor-summary.txt \
    /tmp/verify-core-provider-list.txt \
    /tmp/verify-core-config-get.txt \
    /tmp/verify-core-provider-restore.txt \
    /tmp/verify-core-provider-restore-probe.txt \
    /tmp/verify-core-provider-restore-list.txt \
    /tmp/verify-core-provider-mutation-switch.txt \
    /tmp/verify-core-provider-mutation-list.txt \
    /tmp/verify-core-config-mutation-set.txt \
    /tmp/verify-core-config-mutation-get.txt \
    /tmp/verify-core-channel-connect.txt \
    /tmp/verify-core-shell-list.txt \
    /tmp/verify-core-shell-run.txt \
    /tmp/verify-core-guardrail.txt \
    /tmp/verify-core-browse-policy.txt \
    /tmp/verify-core-context-add.txt \
    /tmp/verify-core-context-list.txt \
    /tmp/verify-core-context-ask.txt \
    /tmp/verify-core-context-noctx-ask.txt \
    /tmp/verify-core-context-clear-after.txt \
    /tmp/verify-core-playbook-scaffold.txt \
    /tmp/verify-core-playbook-add.txt \
    /tmp/verify-core-playbook-list.txt \
    /tmp/verify-core-playbook-show.txt \
    /tmp/verify-core-playbook-run.txt \
    /tmp/verify-core-playbook-capture.txt \
    /tmp/verify-core-playbook-captured-show.txt \
    /tmp/verify-core-playbook-every.txt \
    /tmp/verify-core-playbook-schedules.txt \
    /tmp/verify-core-playbook-run-scheduled.txt \
    /tmp/verify-core-files-add.txt \
    /tmp/verify-core-files-list.txt \
    /tmp/verify-core-files-ask.txt \
    /tmp/verify-core-files-clear-after.txt \
    /tmp/verify-core-ask.txt \
    /tmp/verify-core-attach.txt \
    /tmp/verify-core-export.txt \
    /tmp/verify-core-session-export.txt \
    /tmp/verify-core-session-archive.txt \
    /tmp/verify-core-session-resume.txt \
    /tmp/verify-core-session-resume-files.txt \
    /tmp/verify-core-session-resume-context.txt \
    /tmp/verify-core-session-resume-context-files.txt \
    /tmp/verify-core-session-reuse.txt \
    /tmp/verify-core-session-reuse-files.txt \
    /tmp/verify-core-session-reuse-context.txt \
    /tmp/verify-core-session-reuse-context-files.txt <<'PY'
import json, os, re, sys
from datetime import datetime, timezone

out_path = sys.argv[1]
paths = {
    "web_status": sys.argv[2],
    "schedule_status": sys.argv[3],
    "doctor": sys.argv[4],
    "doctor_summary": sys.argv[5],
    "provider_list": sys.argv[6],
    "config_get": sys.argv[7],
    "provider_restore": sys.argv[8],
    "provider_restore_probe": sys.argv[9],
    "provider_restore_list": sys.argv[10],
    "provider_mutation_switch": sys.argv[11],
    "provider_mutation_list": sys.argv[12],
    "config_mutation_set": sys.argv[13],
    "config_mutation_get": sys.argv[14],
    "channel_connect": sys.argv[15],
    "shell_list": sys.argv[16],
    "shell_run": sys.argv[17],
    "research_guardrail": sys.argv[18],
    "browse_policy": sys.argv[19],
    "context_add": sys.argv[20],
    "context_list": sys.argv[21],
    "context_ask": sys.argv[22],
    "context_noctx_ask": sys.argv[23],
    "context_clear": sys.argv[24],
    "playbook_scaffold": sys.argv[25],
    "playbook_add": sys.argv[26],
    "playbook_list": sys.argv[27],
    "playbook_show": sys.argv[28],
    "playbook_run": sys.argv[29],
    "playbook_capture": sys.argv[30],
    "playbook_captured_show": sys.argv[31],
    "playbook_every": sys.argv[32],
    "playbook_schedules": sys.argv[33],
    "playbook_run_scheduled": sys.argv[34],
    "files_add": sys.argv[35],
    "files_list": sys.argv[36],
    "files_ask": sys.argv[37],
    "files_clear": sys.argv[38],
    "ask": sys.argv[39],
    "attachment_flow": sys.argv[40],
    "artifact_export": sys.argv[41],
    "session_export": sys.argv[42],
    "session_archive": sys.argv[43],
    "session_resume": sys.argv[44],
    "session_resume_files": sys.argv[45],
    "session_resume_context": sys.argv[46],
    "session_resume_context_files": sys.argv[47],
    "session_reuse": sys.argv[48],
    "session_reuse_files": sys.argv[49],
    "session_reuse_context": sys.argv[50],
    "session_reuse_context_files": sys.argv[51],
}

sections = {}
for key, path in paths.items():
    with open(path, encoding="utf-8") as fh:
        sections[key] = fh.read()

def _extract_int(pattern, text, default=0):
    match = re.search(pattern, text, re.MULTILINE)
    return int(match.group(1)) if match else default

def _extract_text(pattern, text, default=""):
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else default

summary = {
    "web_ok": (
        any(token in sections["web_status"] for token in ("gateway:        ok", "gateway:        pid-file"))
        and any(token in sections["web_status"] for token in ("workspace:      ok", "workspace:      pid-file", "workspace:      auth-gated"))
        and any(token in sections["web_status"] for token in ("peer_workspace: ok", "peer_workspace: pid-file", "peer_workspace: auth-gated"))
    ),
    "schedule_surface_ok": "schedule runtime" in sections["schedule_status"],
    "doctor_surface_ok": (
        ("[core] runtime doctor" in sections["doctor"] or "[core] doctor fix:" in sections["doctor"] or "[core] doctor receipt:" in sections["doctor"])
        and "[core] doctor summary" in sections["doctor_summary"]
        and "CRITICAL=0" in sections["doctor_summary"]
    ),
    "provider_surface_ok": "Meridian Provider Plane" in sections["provider_list"],
    "config_surface_ok": "MERIDIAN_GATEWAY_URL=" in sections["config_get"],
    "provider_restore_ok": (
        "[core] provider fix" in sections["provider_restore"]
        and "[core] provider restore" in sections["provider_restore"]
        and "ok:           True" in sections["provider_restore_probe"]
        and "route_id:     route_primary" in sections["provider_restore_probe"]
        and "provider:    manager_primary" in sections["provider_restore_list"]
        and "source:    institution_policy" in sections["provider_restore_list"]
        and "health:      healthy" in sections["provider_restore_list"]
        and "core_manager_local" not in sections["provider_restore_list"]
    ),
    "provider_mutation_ok": "[core] provider switched" in sections["provider_mutation_switch"] and "core_proof_provider" in sections["provider_mutation_list"] and "core-proof-model" in sections["provider_mutation_list"],
    "config_mutation_ok": "MERIDIAN_GATEWAY_URL=http://127.0.0.1:9999" in sections["config_mutation_get"] and "overrides.env" in sections["config_mutation_get"],
    "channel_connect_surface_ok": "connect_listed" in sections["channel_connect"],
    "shell_surface_ok": "shell presets" in sections["shell_list"],
    "research_guardrail_ok": "not allowed" in sections["research_guardrail"],
    "browse_policy_ok": "allowed_schemes: http, https" in sections["browse_policy"],
    "context_surface_ok": (
        "total_files:     1" in sections["context_list"]
        and "context-proof-ok" in sections["context_ask"]
        and "no-context-proof-ok" in sections["context_noctx_ask"]
        and "[core] context files cleared" in sections["context_clear"]
    ),
    "playbook_surface_ok": (
        "[core] playbook scaffolded:" in sections["playbook_scaffold"]
        and "[core] playbook saved:" in sections["playbook_add"]
        and "release-qa" in sections["playbook_list"]
        and "Return exactly: playbook-proof-ok" in sections["playbook_show"]
        and "playbook-proof-ok" in sections["playbook_run"]
        and "[core] playbook captured:" in sections["playbook_capture"]
        and "playbook-proof-ok" in sections["playbook_captured_show"]
        and "[core] playbook schedule mapped:" in sections["playbook_every"]
        and "playbook-release-qa" in sections["playbook_schedules"]
        and "playbook:release-qa" in sections["playbook_schedules"]
        and "playbook-proof-ok" in sections["playbook_run_scheduled"]
    ),
    "files_surface_ok": "total_files:     2" in sections["files_list"] and "queued-proof-ok" in sections["files_ask"],
    "ask_ok": "core-proof-ok" in sections["ask"],
    "attachment_ok": "attach-proof-ok" in sections["attachment_flow"],
    "artifact_export_ok": "written_files: 1" in sections["artifact_export"],
    "session_export_ok": "session.json" in sections["session_export"],
    "session_archive_ok": "[core]" in sections["session_archive"],
    "session_resume_ok": (
        "[core] resumed context written:" in sections["session_resume"]
        and "[core] resumed context queued: True" in sections["session_resume"]
        and "last_resume.txt" in sections["session_resume_files"]
        and "[core] resumed context added to persistent context: True" in sections["session_resume_context"]
        and "last_resume.txt" in sections["session_resume_context_files"]
    ),
    "session_reuse_ok": (
        "[core] reused context written:" in sections["session_reuse"]
        and "[core] reused context queued: True" in sections["session_reuse"]
        and "last_resume.txt" in sections["session_reuse_files"]
        and "core-proof-ok" in sections["session_reuse"]
        and "[core] reused context added to persistent context: True" in sections["session_reuse_context"]
        and "last_resume.txt" in sections["session_reuse_context_files"]
    ),
}

details = {
    "schedule_total": _extract_int(r"total:\s+(\d+)", sections["schedule_status"]),
    "doctor_mode": _extract_text(r"mode:\s+(.+)", sections["doctor_summary"]),
    "doctor_service_health": _extract_text(r"effective_service:\s+([^\s]+)", sections["doctor_summary"]) or _extract_text(r"service:\s+running=\w+\s+health=([^\s]+)", sections["doctor_summary"]),
    "provider_status": _extract_text(r"policy_status:\s+(.+)", sections["provider_list"]),
    "provider_source": _extract_text(r"source:\s+(.+)", sections["provider_list"]),
    "provider_restore_status": _extract_text(r"policy_status:\s+(.+)", sections["provider_restore_list"]),
    "config_gateway_url": _extract_text(r"MERIDIAN_GATEWAY_URL=([^\s]+)", sections["config_get"]),
    "provider_mutation_model": _extract_text(r"model:\s+(.+)", sections["provider_mutation_list"]),
    "config_mutation_gateway_url": _extract_text(r"MERIDIAN_GATEWAY_URL=([^\s]+)", sections["config_mutation_get"]),
    "channel_adapter_count": _extract_int(r"total_adapters:\s+(\d+)", sections["channel_connect"]),
    "context_files_count": _extract_int(r"total_files:\s+(\d+)", sections["context_list"]),
    "playbook_count": _extract_int(r"total:\s+(\d+)", sections["playbook_list"]),
    "playbook_schedule_count": _extract_int(r"total:\s+(\d+)", sections["playbook_schedules"]),
    "queued_files_count": _extract_int(r"total_files:\s+(\d+)", sections["files_list"]),
    "session_export_event_count": _extract_int(r"event_count:\s+(\d+)", sections["session_export"]),
    "session_resume_queue_count": _extract_int(r"total_files:\s+(\d+)", sections["session_resume_files"]),
    "session_resume_context_count": _extract_int(r"total_files:\s+(\d+)", sections["session_resume_context_files"]),
    "session_reuse_queue_count": _extract_int(r"total_files:\s+(\d+)", sections["session_reuse_files"]),
    "session_reuse_context_count": _extract_int(r"total_files:\s+(\d+)", sections["session_reuse_context_files"]),
    "ingress_pending_count": len([name for name in os.listdir("runtime/default/run/ingress/requests") if name.endswith(".json")]) if os.path.isdir("runtime/default/run/ingress/requests") else 0,
    "ingress_quarantine_count": len([name for name in os.listdir("runtime/default/run/ingress/quarantine") if name.endswith(".json")]) if os.path.isdir("runtime/default/run/ingress/quarantine") else 0,
}

failed_checks = sorted(key for key, value in summary.items() if not value)
status = "pass" if not failed_checks else "fail"

payload = {
    "schema_version": "meridian.core.proof.v1",
    "status": status,
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "summary": summary,
    "details": details,
    "failed_checks": failed_checks,
    "sections": sections,
}
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
fi

echo
if [ -n "$OUT_PATH" ]; then
  python3 - "$OUT_PATH" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
status = str(payload.get("status") or "fail")
if status != "pass":
    failed = ", ".join(payload.get("failed_checks") or [])
    print(f"[verify-core] RESULT: FAIL ({failed})")
    raise SystemExit(1)
print("[verify-core] RESULT: PASS")
PY
else
  echo "[verify-core] RESULT: PASS"
fi
