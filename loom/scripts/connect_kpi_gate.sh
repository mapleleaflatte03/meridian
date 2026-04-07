#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOOM_BIN="${REPO_ROOT}/target/debug/loom"

ROOT=""
RETENTION_DAYS=30
UPTIME_TARGET=0.995
FALLBACK_TARGET=0.98
SETTLEMENT_MAX_MS=5000
REQUIRE_SETTLEMENT_LATENCY=false
SKIP_SECURITY_CHECK=false
MIN_TEST_EVENTS=20
ADAPTER_IDS=()

usage() {
  cat <<'USAGE'
Usage:
  connect_kpi_gate.sh --root <runtime-root> --adapter-id <id> [--adapter-id <id> ...]

Options:
  --retention-days <n>              Metrics retention window (default: 30)
  --uptime-target <ratio>           Target uptime ratio (default: 0.995)
  --fallback-target <ratio>         Target fallback success ratio (default: 0.98)
  --settlement-max-ms <n>           Max settlement latency in ms (default: 5000)
  --require-settlement-latency      Fail when settlement latency is unavailable
  --skip-security-check             Skip connect validate security posture gate
  --min-test-events <n>             Minimum tests_total before KPI gating applies (default: 20)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT="${2:-}"; shift 2 ;;
    --adapter-id)
      ADAPTER_IDS+=("${2:-}"); shift 2 ;;
    --retention-days)
      RETENTION_DAYS="${2:-}"; shift 2 ;;
    --uptime-target)
      UPTIME_TARGET="${2:-}"; shift 2 ;;
    --fallback-target)
      FALLBACK_TARGET="${2:-}"; shift 2 ;;
    --settlement-max-ms)
      SETTLEMENT_MAX_MS="${2:-}"; shift 2 ;;
    --require-settlement-latency)
      REQUIRE_SETTLEMENT_LATENCY=true; shift ;;
    --skip-security-check)
      SKIP_SECURITY_CHECK=true; shift ;;
    --min-test-events)
      MIN_TEST_EVENTS="${2:-}"; shift 2 ;;
    --help|-h)
      usage; exit 0 ;;
    *)
      echo "unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${ROOT}" || ${#ADAPTER_IDS[@]} -eq 0 ]]; then
  usage
  exit 2
fi

if [[ ! -x "${LOOM_BIN}" ]]; then
  echo "loom binary missing at ${LOOM_BIN}. Run: cargo build -p meridian-loom" >&2
  exit 2
fi

FAILURES=0

for ADAPTER_ID in "${ADAPTER_IDS[@]}"; do
  METRICS_JSON="$("${LOOM_BIN}" connect metrics \
    --adapter-id "${ADAPTER_ID}" \
    --retention-days "${RETENTION_DAYS}" \
    --root "${ROOT}" \
    --format json)"

  if ! python3 - <<'PY' "${METRICS_JSON}" "${ADAPTER_ID}" "${UPTIME_TARGET}" "${FALLBACK_TARGET}" "${MIN_TEST_EVENTS}"
import json
import sys

payload = json.loads(sys.argv[1])
adapter_id = sys.argv[2]
uptime_target = float(sys.argv[3])
fallback_target = float(sys.argv[4])
min_test_events = int(sys.argv[5])

if payload.get("status") != "connect_metrics":
    raise SystemExit(f"{adapter_id}: unexpected metrics status {payload.get('status')}")

tests_total = int(payload.get("tests_total") or 0)
if tests_total < min_test_events:
    print(f"{adapter_id}: tests_total={tests_total} below min_test_events={min_test_events} (skip KPI gate)")
    raise SystemExit(0)

uptime = float(payload.get("uptime_ratio") or 0.0)
fallback = float(payload.get("fallback_success_ratio") or 0.0)

if uptime < uptime_target:
    raise SystemExit(f"{adapter_id}: uptime_ratio {uptime:.4f} < target {uptime_target:.4f}")
if fallback < fallback_target:
    raise SystemExit(f"{adapter_id}: fallback_success_ratio {fallback:.4f} < target {fallback_target:.4f}")

print(f"{adapter_id}: tests_total={tests_total} uptime={uptime:.4f} fallback_success={fallback:.4f}")
PY
  then
    FAILURES=$((FAILURES + 1))
  fi

  if [[ "${SKIP_SECURITY_CHECK}" != "true" ]]; then
    VALIDATE_JSON="$("${LOOM_BIN}" connect validate \
      --adapter-id "${ADAPTER_ID}" \
      --root "${ROOT}" \
      --format json || true)"
    if ! python3 - <<'PY' "${VALIDATE_JSON}" "${ADAPTER_ID}"
import json
import sys

payload = json.loads(sys.argv[1])
adapter_id = sys.argv[2]

if payload.get("status") != "connect_validated":
    raise SystemExit(f"{adapter_id}: unexpected validate status {payload.get('status')}")

checks = payload.get("checks") or []
if len(checks) != 1:
    raise SystemExit(f"{adapter_id}: expected exactly one validate check row")
row = checks[0]
if not bool(row.get("security_posture_ok")):
    raise SystemExit(f"{adapter_id}: security_posture_ok=false")
if not bool(row.get("valid")):
    raise SystemExit(f"{adapter_id}: validate row marked invalid")

print(f"{adapter_id}: security_posture_ok=true")
PY
    then
      FAILURES=$((FAILURES + 1))
    fi
  fi
done

SETTLEMENT_PATH="${ROOT}/artifacts/settlement/latest.json"
if [[ -f "${SETTLEMENT_PATH}" ]]; then
  if ! python3 - <<'PY' "${SETTLEMENT_PATH}" "${SETTLEMENT_MAX_MS}" "${REQUIRE_SETTLEMENT_LATENCY}"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
limit_ms = int(sys.argv[2])
require_latency = sys.argv[3].lower() == "true"

payload = json.loads(path.read_text())
latency = payload.get("settlement_latency_ms")

if latency is None:
    if require_latency:
        raise SystemExit("settlement_latency_ms missing in settlement artifact")
    print("settlement: latency field missing (skip gate)")
    raise SystemExit(0)

latency = int(latency)
if latency > limit_ms:
    raise SystemExit(f"settlement latency {latency}ms exceeds max {limit_ms}ms")
print(f"settlement: latency={latency}ms")
PY
  then
    FAILURES=$((FAILURES + 1))
  fi
else
  if [[ "${REQUIRE_SETTLEMENT_LATENCY}" == "true" ]]; then
    echo "settlement artifact missing: ${SETTLEMENT_PATH}" >&2
    FAILURES=$((FAILURES + 1))
  else
    echo "settlement artifact missing (skip gate): ${SETTLEMENT_PATH}"
  fi
fi

if [[ ${FAILURES} -gt 0 ]]; then
  echo "connect KPI gate FAILED (${FAILURES} checks)" >&2
  exit 1
fi

echo "connect KPI gate PASS"
