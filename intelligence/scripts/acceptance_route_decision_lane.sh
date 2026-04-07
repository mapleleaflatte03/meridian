#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[meridian-acceptance] route_decision_lane"
cd "${WORKSPACE_ROOT}"
MERIDIAN_MANAGER_AGENT_NAME=Manager "${PYTHON_BIN}" -m unittest \
  company.meridian_platform.test_brain_router.BrainRouterTests.test_execute_manager_http_failover_trace_is_deterministic \
  test_gateway_team_route.GatewayTeamRouteTests.test_route_decision_trace_payload_includes_load_adaptive_thresholds
echo "[meridian-acceptance] PASS route_decision_lane"
