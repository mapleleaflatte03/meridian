#!/usr/bin/env bash
# team-governed-execution.sh — Demonstrate Team governed execution depth
#
# Requires: Team mode onboarding + dev-up.sh running
# Run: bash examples/team-governed-execution.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="http://127.0.0.1:18901"

echo "=== Meridian Team Governed Execution Example ==="
echo ""

# Check if workspace is running
if ! curl -fsS "${WORKSPACE}/api/status" >/dev/null 2>&1; then
  echo "[error] Workspace not running at ${WORKSPACE}."
  echo "        Start with: ./scripts/dev-up.sh"
  exit 1
fi

# Check mode
MODE=$(python3 -c "
import json, os
state_path = os.path.join('${ROOT_DIR}', 'runtime', 'onboard_state.json')
try:
    d = json.load(open(state_path))
    print(d.get('mode', 'unknown'))
except: print('unknown')
" 2>/dev/null || echo "unknown")

if [ "$MODE" != "team" ]; then
  echo "[error] Onboarding mode is '${MODE}', not 'team'."
  echo "        Re-run: ./scripts/onboard.sh --mode team"
  exit 1
fi

echo "1. Run a governed execution..."
RESULT=$(curl -s -X POST "${WORKSPACE}/api/team/governed-execution" \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_id":"example_agent",
    "task_description":"Team example: governed memo preparation",
    "amount_usd":10.0,
    "proof_receipt":"proof_example",
    "assigned_by":"example_user",
    "settled_by":"example_user",
    "estimated_cost_usd":0.15
  }')
echo "   Result: $(echo "$RESULT" | python3 -m json.tool 2>/dev/null || echo "$RESULT")"
echo ""

echo "2. Inspect governance state..."
INSPECT=$(curl -s "${WORKSPACE}/api/team/governed-execution/inspect?agent_id=example_agent")
echo "   Governance: $(echo "$INSPECT" | python3 -m json.tool 2>/dev/null || echo "$INSPECT")"
echo ""

echo "3. Export audit artifact..."
AUDIT=$(curl -s "${WORKSPACE}/api/team/governed-execution/audit-export?agent_id=example_agent")
echo "   Audit: $(echo "$AUDIT" | python3 -m json.tool 2>/dev/null || echo "$AUDIT")"
echo ""

echo "=== Team governed execution example complete ==="
echo "This demonstrates the Team-only depth: policy enforcement, inspect, audit export."
echo "Core mode cannot access these surfaces — they are gated by onboarding mode."
