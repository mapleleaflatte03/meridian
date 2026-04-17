#!/usr/bin/env bash
# team-governed-execution.sh — Demonstrate Team governed execution depth
#
# Requires:
#   - Team mode onboarding (./scripts/onboard.sh --mode team)
#   - Workspace running (./scripts/dev-up.sh)
#
# Team routes require Basic auth. This example reads credentials from:
#   - MERIDIAN_WORKSPACE_USER / MERIDIAN_WORKSPACE_PASS env vars, OR
#   - runtime/workspace_credentials (created by dev-up.sh)
#
# Run: bash examples/team-governed-execution.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${MERIDIAN_WORKSPACE_URL:-http://127.0.0.1:18901}"
CRED_FILE="${MERIDIAN_WORKSPACE_CREDENTIALS_FILE:-${ROOT_DIR}/runtime/workspace_credentials}"

resolve_workspace_credentials() {
  local user="${MERIDIAN_WORKSPACE_USER:-}"
  local pass="${MERIDIAN_WORKSPACE_PASS:-}"
  if [ -n "$user" ] && [ -n "$pass" ]; then
    printf '%s:%s' "$user" "$pass"
    return 0
  fi
  if [ -r "$CRED_FILE" ]; then
    local file_user file_pass
    file_user="$(awk -F': *' '/^user:/ {print $2; exit}' "$CRED_FILE" | tr -d '\r\n')"
    file_pass="$(awk -F': *' '/^pass:/ {print $2; exit}' "$CRED_FILE" | tr -d '\r\n')"
    if [ -n "$file_user" ] && [ -n "$file_pass" ]; then
      printf '%s:%s' "$file_user" "$file_pass"
      return 0
    fi
  fi
  return 1
}

echo "=== Meridian Team Governed Execution Example ==="
echo ""

if ! curl -fsS "${WORKSPACE}/api/status" >/dev/null 2>&1; then
  echo "[error] Workspace not running at ${WORKSPACE}."
  echo "        Start with: ./scripts/dev-up.sh"
  exit 1
fi

MODE="$(python3 -c "
import json, os
state_path = os.path.join('${ROOT_DIR}', 'runtime', 'onboard_state.json')
try:
    d = json.load(open(state_path))
    print(d.get('mode', 'unknown'))
except Exception:
    print('unknown')
" 2>/dev/null || echo unknown)"

if [ "$MODE" != "team" ]; then
  echo "[error] Onboarding mode is '${MODE}', not 'team'."
  echo "        Re-run: ./scripts/onboard.sh --mode team"
  exit 1
fi

if ! AUTH="$(resolve_workspace_credentials)"; then
  echo "[error] Could not resolve workspace credentials."
  echo "        Either set MERIDIAN_WORKSPACE_USER / MERIDIAN_WORKSPACE_PASS,"
  echo "        or start the workspace via ./scripts/dev-up.sh which creates"
  echo "        ${CRED_FILE}."
  exit 1
fi

echo "1. Run a governed execution..."
RESULT="$(curl -fsS -u "$AUTH" -X POST "${WORKSPACE}/api/team/governed-execution" \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_id":"example_agent",
    "task_description":"Team example: governed memo preparation",
    "amount_usd":10.0,
    "proof_receipt":"proof_example",
    "assigned_by":"example_user",
    "settled_by":"example_user",
    "estimated_cost_usd":0.15
  }' || true)"
echo "   Result: $(echo "$RESULT" | python3 -m json.tool 2>/dev/null || echo "$RESULT")"
echo ""

echo "2. Inspect governance state..."
INSPECT="$(curl -fsS -u "$AUTH" "${WORKSPACE}/api/team/governed-execution/inspect?agent_id=example_agent" || true)"
echo "   Governance: $(echo "$INSPECT" | python3 -m json.tool 2>/dev/null || echo "$INSPECT")"
echo ""

echo "3. Export audit artifact..."
AUDIT="$(curl -fsS -u "$AUTH" "${WORKSPACE}/api/team/governed-execution/audit-export?agent_id=example_agent" || true)"
echo "   Audit: $(echo "$AUDIT" | python3 -m json.tool 2>/dev/null || echo "$AUDIT")"
echo ""

echo "=== Team governed execution example complete ==="
echo "This demonstrates the Team-only depth: policy enforcement, inspect, audit export."
echo "Core mode cannot access these surfaces — they are gated by onboarding mode."
