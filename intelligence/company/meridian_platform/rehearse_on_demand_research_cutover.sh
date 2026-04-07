#!/usr/bin/env bash
set -euo pipefail

WORKSPACE=${WORKSPACE:-/home/ubuntu/.meridian/workspace}
ENV_FILE=${ENV_FILE:-/etc/default/meridian-mcp-runtime}
TOPIC_TEXT=${TOPIC_TEXT:-OpenAI pricing}
TOPIC_URL=${TOPIC_URL:-https://app.welliam.codes/api/sample-brief}
RESTART_CHECK=0

if [[ "${1:-}" == "--restart-check" ]]; then
  RESTART_CHECK=1
fi

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ "$RESTART_CHECK" == "1" ]]; then
  sudo -n systemctl restart meridian-mcp.service
  sudo -n systemctl is-active meridian-mcp.service
fi

run_case() {
  local label=$1
  local route_runtime=$2
  local fallback=$3
  local capability=$4
  local topic=$5
  echo "== ${label} =="
  sudo -n env \
    MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_RUNTIME="$route_runtime" \
    MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_ALLOW_FALLBACK="$fallback" \
    MERIDIAN_LOOM_RESEARCH_CAPABILITY="$capability" \
    MERIDIAN_LOOM_BIN="${MERIDIAN_LOOM_BIN:-/home/ubuntu/.local/share/meridian-loom/current/bin/loom}" \
    MERIDIAN_LOOM_ROOT="${MERIDIAN_LOOM_ROOT:-/home/ubuntu/.local/share/meridian-loom/runtime/default}" \
    MERIDIAN_LOOM_AGENT_ID="${MERIDIAN_LOOM_AGENT_ID:-agent_leviathann}" \
    MERIDIAN_LOOM_SERVICE_TOKEN="${MERIDIAN_LOOM_SERVICE_TOKEN:-${LOOM_SERVICE_TOKEN:-}}" \
    LOOM_SERVICE_TOKEN="${LOOM_SERVICE_TOKEN:-${MERIDIAN_LOOM_SERVICE_TOKEN:-}}" \
    CUTOVER_TOPIC="$topic" \
    CUTOVER_DEPTH="${CUTOVER_DEPTH}" \
    python3 - <<'INNER_PY'
import importlib.util
import json
import os
import pathlib
import sys

workspace = pathlib.Path('/home/ubuntu/.meridian/workspace')
company_dir = workspace / 'company'
if str(company_dir) not in sys.path:
    sys.path.insert(0, str(company_dir))
module_path = company_dir / 'mcp_server.py'
spec = importlib.util.spec_from_file_location('meridian_mcp_server_cutover', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

topic = os.environ['CUTOVER_TOPIC']
result = module.do_on_demand_research_route(topic, os.environ.get('CUTOVER_DEPTH', 'quick'))
print(json.dumps(result, indent=2))
INNER_PY
  echo
}

export CUTOVER_DEPTH=quick
run_case off_path legacy 0 "${MERIDIAN_LOOM_RESEARCH_CAPABILITY:-clawskill.safe-web-research.v0}" "$TOPIC_TEXT"
run_case loom_on_path loom 0 "${MERIDIAN_LOOM_RESEARCH_CAPABILITY:-clawskill.safe-web-research.v0}" "$TOPIC_URL"
run_case rollback_path loom 1 "missing.capability.v0" "$TOPIC_TEXT"

sudo -n env \
  MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_RUNTIME="${MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_RUNTIME:-legacy}" \
  MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_ALLOW_FALLBACK="${MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_ALLOW_FALLBACK:-0}" \
  MERIDIAN_LOOM_RESEARCH_CAPABILITY="${MERIDIAN_LOOM_RESEARCH_CAPABILITY:-clawskill.safe-web-research.v0}" \
  MERIDIAN_LOOM_BIN="${MERIDIAN_LOOM_BIN:-/home/ubuntu/.local/share/meridian-loom/current/bin/loom}" \
  MERIDIAN_LOOM_ROOT="${MERIDIAN_LOOM_ROOT:-/home/ubuntu/.local/share/meridian-loom/runtime/default}" \
  MERIDIAN_LOOM_AGENT_ID="${MERIDIAN_LOOM_AGENT_ID:-agent_leviathann}" \
  MERIDIAN_LOOM_SERVICE_TOKEN="${MERIDIAN_LOOM_SERVICE_TOKEN:-${LOOM_SERVICE_TOKEN:-}}" \
  LOOM_SERVICE_TOKEN="${LOOM_SERVICE_TOKEN:-${MERIDIAN_LOOM_SERVICE_TOKEN:-}}" \
  python3 /home/ubuntu/.meridian/workspace/company/meridian_platform/readiness.py --json
