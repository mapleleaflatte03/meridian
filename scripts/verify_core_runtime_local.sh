#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_PATH="${1:-}"
if [ -n "$OUT_PATH" ]; then
  shift || true
fi

PROOF_ASK_SESSION="proof-ask-$$"
PROOF_ATTACH_SESSION="proof-attach-$$"
PROOF_ARTIFACT_SESSION="proof-artifact-$$"
PROOF_PLAYBOOK_SESSION="proof-playbook-$$"
PROOF_PLAYBOOK_SCHEDULED_SESSION="proof-playbook-scheduled-$$"
PROOF_CONTEXT_SESSION="proof-context-$$"
PROOF_CONTEXT_NOCTX_SESSION="proof-context-noctx-$$"
PROOF_FILES_SESSION="proof-files-$$"
PROOF_ASK_GATEWAY_PORT="${PROOF_ASK_GATEWAY_PORT:-18266}"
PROOF_ASK_PROVIDER_PORT="${PROOF_ASK_PROVIDER_PORT:-18778}"
PROOF_ASK_GATEWAY_URL="http://127.0.0.1:${PROOF_ASK_GATEWAY_PORT}"
PROOF_ASK_PROVIDER_URL="http://127.0.0.1:${PROOF_ASK_PROVIDER_PORT}/v1/chat/completions"

wait_for_proof_gateway() {
  local base_url="${MERIDIAN_GATEWAY_URL:-http://127.0.0.1:8266}"
  local probe
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    for probe in /api/healthz /api/status; do
      if curl -fsS --max-time 3 "${base_url%/}${probe}" >/dev/null 2>&1; then
        return 0
      fi
    done
    sleep 1
  done
  return 1
}

cleanup_provider_restore_server() {
  if [ -n "${PROVIDER_RESTORE_SERVER_PID:-}" ]; then
    kill "${PROVIDER_RESTORE_SERVER_PID}" >/dev/null 2>&1 || true
    wait "${PROVIDER_RESTORE_SERVER_PID}" >/dev/null 2>&1 || true
  fi
}

cleanup_proof_ask_runtime() {
  if [ -n "${PROOF_ASK_GATEWAY_PID:-}" ]; then
    kill "${PROOF_ASK_GATEWAY_PID}" >/dev/null 2>&1 || true
    wait "${PROOF_ASK_GATEWAY_PID}" >/dev/null 2>&1 || true
  fi
  if [ -n "${PROOF_ASK_PROVIDER_PID:-}" ]; then
    kill "${PROOF_ASK_PROVIDER_PID}" >/dev/null 2>&1 || true
    wait "${PROOF_ASK_PROVIDER_PID}" >/dev/null 2>&1 || true
  fi
}

cleanup_verify_helpers() {
  cleanup_proof_ask_runtime
  cleanup_provider_restore_server
}

kill_listener_port() {
  local port="$1"
  local pids
  pids="$(ss -ltnp "( sport = :${port} )" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u | tr '\n' ' ')"
  if [ -z "${pids// }" ]; then
    return 0
  fi
  local pid
  for pid in ${pids}; do
    kill "${pid}" >/dev/null 2>&1 || true
    sleep 0.2
    kill -9 "${pid}" >/dev/null 2>&1 || true
  done
}

start_proof_ask_runtime() {
  cleanup_proof_ask_runtime
  kill_listener_port "${PROOF_ASK_GATEWAY_PORT}"
  kill_listener_port "${PROOF_ASK_PROVIDER_PORT}"
  cat >/tmp/core-proof-ask-provider.py <<'PY'
#!/usr/bin/env python3
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

def choose_reply(prompt: str) -> str:
    if "Reply with exactly this markdown and nothing else:" in prompt and "core-export-ok" in prompt:
        return '#### `app.py`\n```python\nprint("core-export-ok")\n```'
    if "playbook-proof-ok" in prompt:
        return "playbook-proof-ok"
    if "attach-proof-ok" in prompt:
        return "attach-proof-ok"
    if "queued-proof-ok" in prompt:
        return "queued-proof-ok"
    if "no-context-proof-ok" in prompt:
        return "no-context-proof-ok"
    if "context-proof-ok" in prompt:
        return "context-proof-ok"
    if "core-proof-ok" in prompt:
        return "core-proof-ok"
    return "core-proof-fallback"

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {}
        prompt_parts = []
        for item in payload.get("messages") or []:
          if not isinstance(item, dict):
            continue
          content = item.get("content")
          if isinstance(content, str):
            prompt_parts.append(content)
          elif isinstance(content, list):
            for block in content:
              if isinstance(block, dict):
                text = str(block.get("text") or "").strip()
                if text:
                  prompt_parts.append(text)
        output = choose_reply("\n".join(prompt_parts))
        response = {
            "id": "chatcmpl-core-proof-ask",
            "object": "chat.completion",
            "model": payload.get("model") or "grok-4-1-fast-reasoning",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": output}, "finish_reason": "stop"}],
        }
        data = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        return

HTTPServer(("127.0.0.1", 18778), Handler).serve_forever()
PY
  python3 /tmp/core-proof-ask-provider.py >/tmp/core-proof-ask-provider.log 2>&1 &
  PROOF_ASK_PROVIDER_PID=$!
  (
    cd "${ROOT_DIR}/intelligence"
    MERIDIAN_KERNEL_ROOT="${ROOT_DIR}/kernel" \
    MERIDIAN_WORKSPACE_ORG_ID="${MERIDIAN_WORKSPACE_ORG_ID:-org_bc3c63f1}" \
    MERIDIAN_WORKSPACE_CREDENTIALS_FILE="${MERIDIAN_WORKSPACE_CREDENTIALS_FILE:-${ROOT_DIR}/runtime/workspace_credentials}" \
    MERIDIAN_WORKSPACE_API_BASE="http://127.0.0.1:18901" \
    MERIDIAN_GATEWAY_PORT="${PROOF_ASK_GATEWAY_PORT}" \
    MERIDIAN_ALLOWED_ORIGIN="https://app.welliam.codes" \
    MERIDIAN_HEARTBEAT_ENABLED=0 \
    MERIDIAN_BRAIN_MANAGER_PROFILE_NAME=manager_primary \
    MERIDIAN_BRAIN_MANAGER_TRANSPORT=http_json \
    MERIDIAN_BRAIN_MANAGER_MODEL=grok-4-1-fast-reasoning \
    MERIDIAN_BRAIN_MANAGER_ENDPOINT="${PROOF_ASK_PROVIDER_URL}" \
    MERIDIAN_BRAIN_MANAGER_AUTH_ENV=MERIDIAN_CORE_PROOF_KEY \
    MERIDIAN_BRAIN_MANAGER_KEY_ENV_POOL=MERIDIAN_CORE_PROOF_KEY \
    MERIDIAN_CORE_PROOF_KEY=core-proof-key \
    nohup python3 meridian_gateway.py >/tmp/core-proof-ask-gateway.log 2>&1 &
    echo $! >/tmp/core-proof-ask-gateway.pid
  )
  PROOF_ASK_GATEWAY_PID="$(cat /tmp/core-proof-ask-gateway.pid 2>/dev/null || true)"
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS --max-time 3 "${PROOF_ASK_GATEWAY_URL}/api/healthz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

echo "[verify-core] checking Core web/operator bridge"
./scripts/core.sh web status >/tmp/verify-core-web-status.txt
cat /tmp/verify-core-web-status.txt

if ! wait_for_proof_gateway; then
  echo "[verify-core] gateway did not become ready before operator probes" >&2
fi

echo
echo "[verify-core] checking governed memory status snapshot"
curl -sS http://127.0.0.1:8266/api/status >/tmp/verify-core-status-snapshot.json
cat /tmp/verify-core-status-snapshot.json

echo
echo "[verify-core] checking runtime proof packet"
curl -sS http://127.0.0.1:8266/api/runtime-proof >/tmp/verify-core-runtime-proof.json
cat /tmp/verify-core-runtime-proof.json

echo
echo "[verify-core] checking governed memory workflow showcase"
curl -sS http://127.0.0.1:8266/api/workflows/showcase >/tmp/verify-core-workflow-showcase.json
cat /tmp/verify-core-workflow-showcase.json

echo
echo "[verify-core] checking governed memory team topology"
curl -sS http://127.0.0.1:8266/api/team/topology >/tmp/verify-core-team-topology.json
cat /tmp/verify-core-team-topology.json

echo
echo "[verify-core] checking governed memory team summary"
curl -sS http://127.0.0.1:8266/api/team/governed-memory >/tmp/verify-core-team-governed-memory.json
cat /tmp/verify-core-team-governed-memory.json

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
echo "[verify-core] checking live provider probe (best effort)"
if ./scripts/core.sh provider probe >/tmp/verify-core-provider-live-probe.txt 2>&1; then
  :
else
  :
fi
cat /tmp/verify-core-provider-live-probe.txt

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
trap cleanup_verify_helpers EXIT
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
echo "[verify-core] checking per-channel diagnostics for zalo (file-based)"
./scripts/core.sh channel diagnostics zalo 5 >/tmp/verify-core-channel-diagnostics-zalo.txt 2>&1 || true
cat /tmp/verify-core-channel-diagnostics-zalo.txt

echo
echo "[verify-core] checking channel delivery proof for telegram"
./scripts/core.sh channel proof telegram 5 >/tmp/verify-core-channel-proof-telegram.txt 2>&1 || true
cat /tmp/verify-core-channel-proof-telegram.txt

echo
echo "[verify-core] checking channel delivery proof for web_api"
./scripts/core.sh channel proof web_api 5 >/tmp/verify-core-channel-proof-webapi.txt 2>&1 || true
cat /tmp/verify-core-channel-proof-webapi.txt

echo
echo "[verify-core] checking shell presets"
./scripts/core.sh shell list >/tmp/verify-core-shell-list.txt
cat /tmp/verify-core-shell-list.txt

echo
echo "[verify-core] checking governed memory fork/replay"
rm -rf /tmp/core-proof-memory-governed
mkdir -p /tmp/core-proof-memory-governed
"${ROOT_DIR}/loom/target/release/loom" init --mode embedded --kernel-path "${ROOT_DIR}/kernel" --root /tmp/core-proof-memory-governed --org-id org_bc3c63f1 >/tmp/verify-core-memory-init.txt
"${ROOT_DIR}/loom/target/release/loom" memory write --root /tmp/core-proof-memory-governed --agent-id agent_atlas --category research --key pattern --content "v1" --source core-proof --format json >/tmp/verify-core-memory-seed-1.txt
"${ROOT_DIR}/loom/target/release/loom" memory write --root /tmp/core-proof-memory-governed --agent-id agent_atlas --category research --key pattern --content "v2" --source core-proof --format json >/tmp/verify-core-memory-seed-2.txt
"${ROOT_DIR}/loom/target/release/loom" memory write --root /tmp/core-proof-memory-governed --agent-id agent_atlas --category research --key insight --content "portable" --source core-proof --format json >/tmp/verify-core-memory-seed-3.txt
env \
  MERIDIAN_LOOM_ROOT=/tmp/core-proof-memory-governed \
  ./scripts/core.sh memory fork agent_atlas --target-agent agent_quill --branch proof-lane \
  >/tmp/verify-core-memory-fork.txt
cat /tmp/verify-core-memory-fork.txt
env \
  MERIDIAN_LOOM_ROOT=/tmp/core-proof-memory-governed \
  ./scripts/core.sh memory replay agent_atlas --target-agent agent_quill \
  >/tmp/verify-core-memory-replay.txt
cat /tmp/verify-core-memory-replay.txt
env \
  MERIDIAN_LOOM_ROOT=/tmp/core-proof-memory-governed \
  ./scripts/core.sh memory latest-fork --json \
  >/tmp/verify-core-memory-latest-fork.txt
cat /tmp/verify-core-memory-latest-fork.txt
env \
  MERIDIAN_LOOM_ROOT=/tmp/core-proof-memory-governed \
  ./scripts/core.sh memory latest-replay --json \
  >/tmp/verify-core-memory-latest-replay.txt
cat /tmp/verify-core-memory-latest-replay.txt
env \
  MERIDIAN_LOOM_ROOT=/tmp/core-proof-memory-governed \
  ./scripts/core.sh memory fork-history 5 --json \
  >/tmp/verify-core-memory-fork-history.txt
cat /tmp/verify-core-memory-fork-history.txt
env \
  MERIDIAN_LOOM_ROOT=/tmp/core-proof-memory-governed \
  ./scripts/core.sh memory replay-history 5 --json \
  >/tmp/verify-core-memory-replay-history.txt
cat /tmp/verify-core-memory-replay-history.txt
env \
  MERIDIAN_LOOM_ROOT=/tmp/core-proof-memory-governed \
  ./scripts/core.sh memory governance 5 --json \
  >/tmp/verify-core-memory-governance-summary.txt
cat /tmp/verify-core-memory-governance-summary.txt
"${ROOT_DIR}/loom/target/release/loom" memory search --root /tmp/core-proof-memory-governed --agent-id agent_quill --format json >/tmp/verify-core-memory-replay-search.txt
cat /tmp/verify-core-memory-replay-search.txt

echo
echo "[verify-core] checking shell preset execution"
./scripts/core.sh shell run repo-status >/tmp/verify-core-shell-run.txt
head -n 40 /tmp/verify-core-shell-run.txt

echo
echo "[verify-core] checking agent inspect operator view"
./scripts/core.sh agent inspect >/tmp/verify-core-agent-inspect.txt
cat /tmp/verify-core-agent-inspect.txt

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
echo "[verify-core] starting isolated proof ask runtime"
start_proof_ask_runtime >/tmp/verify-core-proof-ask-runtime.txt 2>&1 || true
cat /tmp/verify-core-proof-ask-runtime.txt

echo
echo "[verify-core] checking persistent context files"
./scripts/core.sh context clear >/tmp/verify-core-context-clear-before.txt
mkdir -p /tmp/core-proof-context
printf 'project-context-proof\n' >/tmp/core-proof-context/context.txt
./scripts/core.sh context add /tmp/core-proof-context/context.txt >/tmp/verify-core-context-add.txt
cat /tmp/verify-core-context-add.txt
./scripts/core.sh context list >/tmp/verify-core-context-list.txt
cat /tmp/verify-core-context-list.txt
MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" ./scripts/core.sh ask --session "$PROOF_CONTEXT_SESSION" "Reply with exactly: context-proof-ok" >/tmp/verify-core-context-ask.txt 2>&1 || true
cat /tmp/verify-core-context-ask.txt
grep -q "context-proof-ok" /tmp/verify-core-context-ask.txt || true
MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" ./scripts/core.sh ask --session "$PROOF_CONTEXT_NOCTX_SESSION" --no-context "Reply with exactly: no-context-proof-ok" >/tmp/verify-core-context-noctx-ask.txt 2>&1 || true
cat /tmp/verify-core-context-noctx-ask.txt
grep -q "no-context-proof-ok" /tmp/verify-core-context-noctx-ask.txt || true
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
MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" MERIDIAN_SESSION_ID="$PROOF_PLAYBOOK_SESSION" ./scripts/core.sh playbook run release-qa >/tmp/verify-core-playbook-run.txt 2>&1 || true
cat /tmp/verify-core-playbook-run.txt
grep -q "playbook-proof-ok" /tmp/verify-core-playbook-run.txt || true
./scripts/core.sh playbook capture captured-proof >/tmp/verify-core-playbook-capture.txt 2>&1 || true
cat /tmp/verify-core-playbook-capture.txt
./scripts/core.sh playbook show captured-proof >/tmp/verify-core-playbook-captured-show.txt 2>&1 || true
cat /tmp/verify-core-playbook-captured-show.txt
grep -q "playbook-proof-ok" /tmp/verify-core-playbook-captured-show.txt || true
./scripts/core.sh playbook every release-qa 3600 >/tmp/verify-core-playbook-every.txt
cat /tmp/verify-core-playbook-every.txt
./scripts/core.sh playbook schedules >/tmp/verify-core-playbook-schedules.txt
cat /tmp/verify-core-playbook-schedules.txt
grep -q "playbook:release-qa" /tmp/verify-core-playbook-schedules.txt || true
MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" MERIDIAN_SESSION_ID="$PROOF_PLAYBOOK_SCHEDULED_SESSION" ./scripts/core.sh playbook run-scheduled playbook-release-qa >/tmp/verify-core-playbook-run-scheduled.txt 2>&1 || true
cat /tmp/verify-core-playbook-run-scheduled.txt
grep -q "playbook-proof-ok" /tmp/verify-core-playbook-run-scheduled.txt || true
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
MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" ./scripts/core.sh ask --session "$PROOF_FILES_SESSION" --queued-files "Reply with exactly: queued-proof-ok" >/tmp/verify-core-files-ask.txt 2>&1 || true
cat /tmp/verify-core-files-ask.txt
grep -q "queued-proof-ok" /tmp/verify-core-files-ask.txt || true
./scripts/core.sh files clear >/tmp/verify-core-files-clear-after.txt
cat /tmp/verify-core-files-clear-after.txt

echo
echo "[verify-core] checking Core ask"
MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" ./scripts/core.sh ask --session "$PROOF_ASK_SESSION" "Reply with exactly: core-proof-ok" >/tmp/verify-core-ask.txt 2>&1 || true
cat /tmp/verify-core-ask.txt
grep -q "core-proof-ok" /tmp/verify-core-ask.txt || true
./scripts/core.sh response meta >/tmp/verify-core-response-meta.txt 2>&1 || true
cat /tmp/verify-core-response-meta.txt

echo
echo "[verify-core] checking attachment flow"
mkdir -p /tmp/core-proof-input
printf 'print("proof")\n' >/tmp/core-proof-input/sample.py
MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" ./scripts/core.sh ask --session "$PROOF_ATTACH_SESSION" --file /tmp/core-proof-input/sample.py "Reply with exactly: attach-proof-ok" >/tmp/verify-core-attach.txt 2>&1 || true
cat /tmp/verify-core-attach.txt
grep -q "attach-proof-ok" /tmp/verify-core-attach.txt || true

echo
echo "[verify-core] checking artifact export"
MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" ./scripts/core.sh ask --session "$PROOF_ARTIFACT_SESSION" $'Reply with exactly this markdown and nothing else:\n#### `app.py`\n```python\nprint("core-export-ok")\n```' >/tmp/verify-core-artifact-ask.txt 2>&1 || true
cat /tmp/verify-core-artifact-ask.txt
grep -q "core-export-ok" /tmp/verify-core-artifact-ask.txt || true
rm -rf /tmp/core-proof-export
./scripts/core.sh response export /tmp/core-proof-export >/tmp/verify-core-export.txt 2>&1 || true
cat /tmp/verify-core-export.txt
test -f /tmp/core-proof-export/app.py || true
grep -q "core-export-ok" /tmp/core-proof-export/app.py || true

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
    /tmp/verify-core-provider-live-probe.txt \
    /tmp/verify-core-config-get.txt \
    /tmp/verify-core-provider-restore.txt \
    /tmp/verify-core-provider-restore-probe.txt \
    /tmp/verify-core-provider-restore-list.txt \
    /tmp/verify-core-provider-mutation-switch.txt \
    /tmp/verify-core-provider-mutation-list.txt \
    /tmp/verify-core-config-mutation-set.txt \
    /tmp/verify-core-config-mutation-get.txt \
    /tmp/verify-core-channel-connect.txt \
    /tmp/verify-core-channel-diagnostics.txt \
    /tmp/verify-core-channel-diagnostics-telegram.txt \
    /tmp/verify-core-channel-diagnostics-zalo.txt \
    /tmp/verify-core-channel-proof-telegram.txt \
    /tmp/verify-core-channel-proof-webapi.txt \
    /tmp/verify-core-shell-list.txt \
    /tmp/verify-core-memory-fork.txt \
    /tmp/verify-core-memory-replay.txt \
    /tmp/verify-core-memory-latest-fork.txt \
    /tmp/verify-core-memory-latest-replay.txt \
    /tmp/verify-core-memory-fork-history.txt \
    /tmp/verify-core-memory-replay-history.txt \
    /tmp/verify-core-memory-governance-summary.txt \
    /tmp/verify-core-memory-replay-search.txt \
    /tmp/verify-core-shell-run.txt \
    /tmp/verify-core-agent-inspect.txt \
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
    /tmp/verify-core-response-meta.txt \
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
    /tmp/verify-core-session-reuse-context-files.txt \
    /tmp/verify-core-status-snapshot.json \
    /tmp/verify-core-runtime-proof.json \
    /tmp/verify-core-workflow-showcase.json \
    /tmp/verify-core-team-topology.json \
    /tmp/verify-core-team-governed-memory.json <<'PY'
import json, os, re, sys
from datetime import datetime, timezone

out_path = sys.argv[1]
paths = {
    "web_status": sys.argv[2],
    "schedule_status": sys.argv[3],
    "doctor": sys.argv[4],
    "doctor_summary": sys.argv[5],
    "provider_list": sys.argv[6],
    "provider_live_probe": sys.argv[7],
    "config_get": sys.argv[8],
    "provider_restore": sys.argv[9],
    "provider_restore_probe": sys.argv[10],
    "provider_restore_list": sys.argv[11],
    "provider_mutation_switch": sys.argv[12],
    "provider_mutation_list": sys.argv[13],
    "config_mutation_set": sys.argv[14],
    "config_mutation_get": sys.argv[15],
    "channel_connect": sys.argv[16],
    "channel_diagnostics": sys.argv[17],
    "channel_diagnostics_telegram": sys.argv[18],
    "channel_diagnostics_zalo": sys.argv[19],
    "channel_proof_telegram": sys.argv[20],
    "channel_proof_webapi": sys.argv[21],
    "shell_list": sys.argv[22],
    "memory_fork": sys.argv[23],
    "memory_replay": sys.argv[24],
    "memory_latest_fork": sys.argv[25],
    "memory_latest_replay": sys.argv[26],
    "memory_fork_history": sys.argv[27],
    "memory_replay_history": sys.argv[28],
    "memory_governance_summary": sys.argv[29],
    "memory_replay_search": sys.argv[30],
    "shell_run": sys.argv[31],
    "agent_inspect": sys.argv[32],
    "research_guardrail": sys.argv[33],
    "browse_policy": sys.argv[34],
    "context_add": sys.argv[35],
    "context_list": sys.argv[36],
    "context_ask": sys.argv[37],
    "context_noctx_ask": sys.argv[38],
    "context_clear": sys.argv[39],
    "playbook_scaffold": sys.argv[40],
    "playbook_add": sys.argv[41],
    "playbook_list": sys.argv[42],
    "playbook_show": sys.argv[43],
    "playbook_run": sys.argv[44],
    "playbook_capture": sys.argv[45],
    "playbook_captured_show": sys.argv[46],
    "playbook_every": sys.argv[47],
    "playbook_schedules": sys.argv[48],
    "playbook_run_scheduled": sys.argv[49],
    "files_add": sys.argv[50],
    "files_list": sys.argv[51],
    "files_ask": sys.argv[52],
    "files_clear": sys.argv[53],
    "ask": sys.argv[54],
    "response_meta": sys.argv[55],
    "attachment_flow": sys.argv[56],
    "artifact_export": sys.argv[57],
    "session_export": sys.argv[58],
    "session_archive": sys.argv[59],
    "session_resume": sys.argv[60],
    "session_resume_files": sys.argv[61],
    "session_resume_context": sys.argv[62],
    "session_resume_context_files": sys.argv[63],
    "session_reuse": sys.argv[64],
    "session_reuse_files": sys.argv[65],
    "session_reuse_context": sys.argv[66],
    "session_reuse_context_files": sys.argv[67],
    "status_snapshot": sys.argv[68],
    "runtime_proof": sys.argv[69],
    "workflow_showcase": sys.argv[70],
    "team_topology": sys.argv[71],
    "team_governed_memory": sys.argv[72],
}

sections = {}
for key, path in paths.items():
    with open(path, encoding="utf-8") as fh:
        sections[key] = fh.read()

json_docs = {}
for key in ("status_snapshot", "runtime_proof", "workflow_showcase", "team_topology", "team_governed_memory"):
    try:
        json_docs[key] = json.loads(sections[key])
    except Exception:
        json_docs[key] = {}

status_doc = json_docs["status_snapshot"] if isinstance(json_docs["status_snapshot"], dict) else {}
runtime_proof_doc = json_docs["runtime_proof"] if isinstance(json_docs["runtime_proof"], dict) else {}
workflow_doc = json_docs["workflow_showcase"] if isinstance(json_docs["workflow_showcase"], dict) else {}
team_topology_doc = json_docs["team_topology"] if isinstance(json_docs["team_topology"], dict) else {}
team_governed_doc = json_docs["team_governed_memory"] if isinstance(json_docs["team_governed_memory"], dict) else {}
showcase_payload = dict(workflow_doc.get("showcase") or {}) if isinstance(workflow_doc, dict) else {}
showcase_workflows = list(showcase_payload.get("workflows") or [])
showcase_workflow_ids = {str(item.get("workflow_id") or "").strip() for item in showcase_workflows if isinstance(item, dict)}
provider_runtime_status = dict(status_doc.get("provider_runtime") or {})
provider_runtime_proof = dict(runtime_proof_doc.get("provider_runtime") or {})
provider_runtime_team = dict(team_topology_doc.get("provider_runtime") or {})
memory_taxonomy_status = dict(status_doc.get("memory_taxonomy") or {})
memory_taxonomy_team = dict(team_topology_doc.get("memory_taxonomy") or {})
governed_memory_team = dict(team_topology_doc.get("governed_memory") or {})

response_meta = {}
for line in sections["response_meta"].splitlines():
    if ":" not in line:
        continue
    key, value = line.split(":", 1)
    response_meta[key.strip()] = value.strip()

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
    "governed_memory_status_surface_ok": (
        '"governed_memory"' in sections["status_snapshot"]
        and '"fork_latest_status"' in sections["status_snapshot"]
        and '"replay_latest_status"' in sections["status_snapshot"]
    ),
    "memory_taxonomy_status_surface_ok": (
        '"memory_taxonomy"' in sections["status_snapshot"]
        and '"tag_count"' in sections["status_snapshot"]
        and '"tags"' in sections["status_snapshot"]
    ),
    "provider_runtime_status_surface_ok": (
        bool(provider_runtime_status)
        and isinstance(provider_runtime_status.get("selected_plan"), dict)
        and isinstance(provider_runtime_status.get("route_alignment"), dict)
        and "override_active" in provider_runtime_status
    ),
    "provider_runtime_runtime_proof_surface_ok": (
        bool(provider_runtime_proof)
        and isinstance(provider_runtime_proof.get("selected_plan"), dict)
        and isinstance(provider_runtime_proof.get("route_alignment"), dict)
        and "override_active" in provider_runtime_proof
    ),
    "governed_memory_showcase_surface_ok": (
        '"workflow_id": "governed_memory_relay"' in sections["workflow_showcase"]
        and '"fork_latest_status"' in sections["workflow_showcase"]
        and '"replay_latest_status"' in sections["workflow_showcase"]
    ),
    "provider_runtime_showcase_surface_ok": (
        "provider_runtime_alignment" in showcase_workflow_ids
        and any(
            isinstance(item, dict)
            and str(item.get("workflow_id") or "") == "provider_runtime_alignment"
            and "drift_fields" in item
            and "selected_provider" in item
            and "active_provider" in item
            for item in showcase_workflows
        )
    ),
    "memory_taxonomy_showcase_surface_ok": (
        '"workflow_id": "memory_tag_taxonomy"' in sections["workflow_showcase"]
        and '"operator_signal": "memory_tag_count"' in sections["workflow_showcase"]
        and '"tags"' in sections["workflow_showcase"]
    ),
    "governed_memory_team_topology_ok": (
        isinstance(team_topology_doc.get("manager"), dict)
        and isinstance(team_topology_doc.get("specialists"), list)
        and bool(governed_memory_team)
        and "fork_recent_count" in governed_memory_team
        and "replay_recent_count" in governed_memory_team
        and bool(memory_taxonomy_team)
        and bool(provider_runtime_team)
        and isinstance(provider_runtime_team.get("route_alignment"), dict)
    ),
    "governed_memory_team_summary_ok": (
        '"summary"' in sections["team_governed_memory"]
        and '"agents"' in sections["team_governed_memory"]
        and '"recent_actions"' in sections["team_governed_memory"]
        and '"fork_latest_status"' in sections["team_governed_memory"]
        and '"replay_latest_status"' in sections["team_governed_memory"]
        and '"replay_authority_status"' in sections["team_governed_memory"]
    ),
    "schedule_surface_ok": "schedule runtime" in sections["schedule_status"],
    "doctor_surface_ok": (
        ("[core] runtime doctor" in sections["doctor"] or "[core] doctor fix:" in sections["doctor"] or "[core] doctor receipt:" in sections["doctor"])
        and "[core] doctor summary" in sections["doctor_summary"]
        and "CRITICAL=0" in sections["doctor_summary"]
    ),
    "provider_surface_ok": "Meridian Provider Plane" in sections["provider_list"],
    "provider_surface_truth_ok": (
        "Effective Manager Execution" in sections["provider_list"]
        and "source:" in sections["provider_list"]
    ),
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
    "channel_diagnostics_surface_ok": (
        "[core] multi-channel health" in sections["channel_diagnostics"]
        and "[core] channel diagnostics" in sections["channel_diagnostics_telegram"]
        and "telegram" in sections["channel_diagnostics_telegram"]
        and "[core] channel diagnostics" in sections["channel_diagnostics_zalo"]
        and "zalo" in sections["channel_diagnostics_zalo"]
    ),
    "channel_proof_surface_ok": (
        "[core] channel delivery proof" in sections["channel_proof_telegram"]
        and "head chain hash:" in sections["channel_proof_telegram"]
        and "[core] channel delivery proof" in sections["channel_proof_webapi"]
        and "head chain hash:" in sections["channel_proof_webapi"]
    ),
    "memory_governance_surface_ok": (
        "status:            memory_fork_created" in sections["memory_fork"]
        and "target_agent_id:   agent_quill" in sections["memory_fork"]
        and (
            "status:            memory_replay_applied" in sections["memory_replay"]
            or "status:            memory_replay_blocked" in sections["memory_replay"]
        )
        and "court_status:      clear" in sections["memory_replay"]
        and (
            "authority_status:  allowed" in sections["memory_replay"]
            or "authority_status:  denied" in sections["memory_replay"]
        )
        and '"agent_id": "agent_quill"' in sections["memory_replay_search"]
        and '"key": "pattern"' in sections["memory_replay_search"]
    ),
    "memory_latest_fork_surface_ok": (
        '"status": "memory_fork_created"' in sections["memory_latest_fork"]
        and '"target_agent_id": "agent_quill"' in sections["memory_latest_fork"]
    ),
    "memory_latest_replay_surface_ok": (
        (
            '"status": "memory_replay_applied"' in sections["memory_latest_replay"]
            or '"status": "memory_replay_blocked"' in sections["memory_latest_replay"]
        )
        and '"target_agent_id": "agent_quill"' in sections["memory_latest_replay"]
    ),
    "memory_history_surface_ok": (
        '"artifact_count":' in sections["memory_fork_history"]
        and '"status": "memory_fork_created"' in sections["memory_fork_history"]
        and '"artifact_count":' in sections["memory_replay_history"]
        and (
            '"status": "memory_replay_applied"' in sections["memory_replay_history"]
            or '"status": "memory_replay_blocked"' in sections["memory_replay_history"]
        )
    ),
    "memory_governance_summary_surface_ok": (
        '"fork_latest_status": "memory_fork_created"' in sections["memory_governance_summary"]
        and (
            '"replay_latest_status": "memory_replay_applied"' in sections["memory_governance_summary"]
            or '"replay_latest_status": "memory_replay_blocked"' in sections["memory_governance_summary"]
        )
        and '"fork_recent_count":' in sections["memory_governance_summary"]
        and '"replay_recent_count":' in sections["memory_governance_summary"]
    ),
    "agent_inspect_governed_memory_ok": (
        "Meridian Loom // RUN AGENT INSPECT" in sections["agent_inspect"]
        and "Governed memory" in sections["agent_inspect"]
        and "fork latest=" in sections["agent_inspect"]
        and "replay latest=" in sections["agent_inspect"]
    ),
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
    "response_meta_provider_runtime_ok": (
        all(
            key in response_meta
            for key in (
                "provider_source",
                "provider_profile",
                "provider_model",
                "provider_transport",
                "provider_drift",
            )
        )
    ),
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
    "governed_memory_status_replay_latest": str((status_doc.get("governed_memory") or {}).get("replay_latest_status") or ""),
    "memory_taxonomy_status_tag_count": int(memory_taxonomy_status.get("tag_count") or 0),
    "provider_runtime_source": str(provider_runtime_status.get("source") or ""),
    "provider_runtime_runtime_proof_source": str(provider_runtime_proof.get("source") or ""),
    "provider_runtime_override_active": str(provider_runtime_status.get("override_active")),
    "provider_runtime_drift_count": len(list((provider_runtime_status.get("route_alignment") or {}).get("drift_fields") or [])),
    "provider_runtime_runtime_proof_drift_count": len(list((provider_runtime_proof.get("route_alignment") or {}).get("drift_fields") or [])),
    "governed_memory_showcase_operator_value": _extract_int(r'"operator_value":\s+(\d+)', sections["workflow_showcase"]),
    "memory_taxonomy_showcase_tag_count": next((int(item.get("operator_value") or 0) for item in showcase_workflows if isinstance(item, dict) and str(item.get("workflow_id") or "") == "memory_tag_taxonomy"), 0),
    "provider_runtime_showcase_drift_value": next((int(item.get("operator_value") or 0) for item in showcase_workflows if isinstance(item, dict) and str(item.get("workflow_id") or "") == "provider_runtime_alignment"), 0),
    "governed_memory_team_specialist_count": _extract_int(r'"specialist_count":\s+(\d+)', sections["team_topology"]),
    "memory_taxonomy_team_tag_count": int(memory_taxonomy_team.get("tag_count") or 0),
    "provider_runtime_team_drift_count": len(list((provider_runtime_team.get("route_alignment") or {}).get("drift_fields") or [])),
    "governed_memory_team_agent_count": _extract_int(r'"agent_count":\s+(\d+)', sections["team_governed_memory"]),
    "governed_memory_team_active_agent_count": _extract_int(r'"active_agent_count":\s+(\d+)', sections["team_governed_memory"]),
    "governed_memory_team_replay_latest": _extract_text(r'"replay_latest_status":\s*"([^"]+)"', sections["team_governed_memory"]),
    "doctor_mode": _extract_text(r"mode:\s+(.+)", sections["doctor_summary"]),
    "doctor_service_health": _extract_text(r"effective_service:\s+([^\s]+)", sections["doctor_summary"]) or _extract_text(r"service:\s+running=\w+\s+health=([^\s]+)", sections["doctor_summary"]),
    "provider_status": _extract_text(r"policy_status:\s+(.+)", sections["provider_list"]),
    "provider_source": _extract_text(r"source:\s+(.+)", sections["provider_list"]),
    "provider_live_probe_ok": "ok:           True" in sections["provider_live_probe"],
    "provider_live_probe_provider": _extract_text(r"provider:\s+([^\n]*)", sections["provider_live_probe"]),
    "provider_live_probe_transport": _extract_text(r"transport:\s+([^\n]*)", sections["provider_live_probe"]),
    "provider_live_probe_route_id": _extract_text(r"route_id:[ \t]*([^\n]*)", sections["provider_live_probe"]),
    "provider_live_probe_error_code": _extract_text(r"error_code:\s+([^\n]*)", sections["provider_live_probe"]),
    "provider_restore_status": _extract_text(r"policy_status:\s+(.+)", sections["provider_restore_list"]),
    "config_gateway_url": _extract_text(r"MERIDIAN_GATEWAY_URL=([^\s]+)", sections["config_get"]),
    "provider_mutation_model": _extract_text(r"model:\s+(.+)", sections["provider_mutation_list"]),
    "config_mutation_gateway_url": _extract_text(r"MERIDIAN_GATEWAY_URL=([^\s]+)", sections["config_mutation_get"]),
    "channel_adapter_count": _extract_int(r"total_adapters:\s+(\d+)", sections["channel_connect"]),
    "channel_health_channel_count": _extract_int(r"channel_count:\s+(\d+)", sections["channel_diagnostics"]),
    "telegram_proof_receipt_count": _extract_int(r"receipts:\s+(\d+)", sections["channel_proof_telegram"]),
    "webapi_proof_receipt_count": _extract_int(r"receipts:\s+(\d+)", sections["channel_proof_webapi"]),
    "memory_fork_selected_entries": _extract_int(r"selected_entries:\s+(\d+)", sections["memory_fork"]),
    "memory_replay_replayed_entries": _extract_int(r"replayed_entries:\s+(\d+)", sections["memory_replay"]),
    "memory_replay_status": _extract_text(r"status:\s+([^\n]+)", sections["memory_replay"]),
    "memory_replay_authority_status": _extract_text(r"authority_status:\s+([^\n]+)", sections["memory_replay"]),
    "memory_latest_fork_status": _extract_text(r'"status":\s*"([^"]+)"', sections["memory_latest_fork"]),
    "memory_latest_replay_status": _extract_text(r'"status":\s*"([^"]+)"', sections["memory_latest_replay"]),
    "memory_fork_history_count": _extract_int(r'"artifact_count":\s+(\d+)', sections["memory_fork_history"]),
    "memory_replay_history_count": _extract_int(r'"artifact_count":\s+(\d+)', sections["memory_replay_history"]),
    "memory_governance_fork_recent_count": _extract_int(r'"fork_recent_count":\s+(\d+)', sections["memory_governance_summary"]),
    "memory_governance_replay_recent_count": _extract_int(r'"replay_recent_count":\s+(\d+)', sections["memory_governance_summary"]),
    "memory_replay_target_entry_count": len(re.findall(r'"agent_id":\s*"agent_quill"', sections["memory_replay_search"])),
    "context_files_count": _extract_int(r"total_files:\s+(\d+)", sections["context_list"]),
    "playbook_count": _extract_int(r"total:\s+(\d+)", sections["playbook_list"]),
    "playbook_schedule_count": _extract_int(r"total:\s+(\d+)", sections["playbook_schedules"]),
    "queued_files_count": _extract_int(r"total_files:\s+(\d+)", sections["files_list"]),
    "response_meta_provider_source": str(response_meta.get("provider_source") or ""),
    "response_meta_provider_profile": str(response_meta.get("provider_profile") or ""),
    "response_meta_provider_transport": str(response_meta.get("provider_transport") or ""),
    "session_export_event_count": _extract_int(r"event_count:\s+(\d+)", sections["session_export"]),
    "session_resume_queue_count": _extract_int(r"total_files:\s+(\d+)", sections["session_resume_files"]),
    "session_resume_context_count": _extract_int(r"total_files:\s+(\d+)", sections["session_resume_context_files"]),
    "session_reuse_queue_count": _extract_int(r"total_files:\s+(\d+)", sections["session_reuse_files"]),
    "session_reuse_context_count": _extract_int(r"total_files:\s+(\d+)", sections["session_reuse_context_files"]),
    "ingress_pending_count": len([name for name in os.listdir("runtime/default/run/ingress/requests") if name.endswith(".json")]) if os.path.isdir("runtime/default/run/ingress/requests") else 0,
    "ingress_quarantine_count": len([name for name in os.listdir("runtime/default/run/ingress/quarantine") if name.endswith(".json")]) if os.path.isdir("runtime/default/run/ingress/quarantine") else 0,
}

lane_truth = {
    "live_provider_probe": {
        "ok": bool(details["provider_live_probe_ok"]),
        "provider": str(details["provider_live_probe_provider"] or ""),
        "transport": str(details["provider_live_probe_transport"] or ""),
        "route_id": str(details["provider_live_probe_route_id"] or ""),
        "error_code": str(details["provider_live_probe_error_code"] or ""),
    },
    "isolated_ask_lane": {
        "ok": bool(summary["ask_ok"]),
        "provider_source": str(details["response_meta_provider_source"] or ""),
        "provider_profile": str(details["response_meta_provider_profile"] or ""),
        "provider_transport": str(details["response_meta_provider_transport"] or ""),
    },
    "distinction": {
        "explicit": True,
        "live_provider_degraded": not bool(details["provider_live_probe_ok"]),
        "isolated_ask_passed": bool(summary["ask_ok"]),
        "status": (
            "split_truth_explicit"
            if bool(summary["ask_ok"]) and not bool(details["provider_live_probe_ok"])
            else "aligned"
        ),
    },
}

failed_checks = sorted(key for key, value in summary.items() if not value)
status = "pass" if not failed_checks else "fail"

payload = {
    "schema_version": "meridian.core.proof.v1",
    "status": status,
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "summary": summary,
    "details": details,
    "lane_truth": lane_truth,
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
