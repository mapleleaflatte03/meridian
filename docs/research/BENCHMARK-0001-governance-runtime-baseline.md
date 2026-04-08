# BENCHMARK-0001: Governance Runtime Baseline

## Goal

Provide a reproducible baseline for local governance/runtime health without requiring private infrastructure.

## Environment Contract

- Host: local Linux machine
- Stack: monorepo bootstrap (`scripts/bootstrap_full.sh`)
- Gateway: `http://127.0.0.1:8266`

## Reproduction Steps

```bash
cd /path/to/meridian
MERIDIAN_SKIP_LOOM_BUILD=1 ./scripts/bootstrap_full.sh
./scripts/dev-up.sh

curl -fsS http://127.0.0.1:8266/api/status | python3 -m json.tool
curl -fsS http://127.0.0.1:8266/api/runtime-proof | python3 -m json.tool
curl -fsS http://127.0.0.1:8266/api/kernel-proof-bundle | python3 -m json.tool
curl -fsS http://127.0.0.1:8266/api/treasury | python3 -m json.tool

# canonical capture script (writes runtime/research/baseline_*.json)
./scripts/research_capture_baseline.sh
```

## Metrics Contract

Record at minimum:

1. `slo.status` from `/api/status`
2. `runtime_id` + proof route presence
3. kernel proof bundle cache state (`fresh`, `stale_fallback`, `building`, etc.)
4. treasury balance + reserve floor
5. sanction counters (open violations / pending appeals)

## Baseline Interpretation

- Healthy baseline means all routes are reachable and semantics are coherent.
- Warning baseline is acceptable if degraded reason is explicit and fallback works.
- Breach baseline requires filing issue with route payload evidence.

## Notes

- This benchmark is boundary-health oriented, not throughput micro-benchmark.
- Results are valid only with command evidence and payload snapshots attached.
- The capture artifact includes only stable route fields to avoid accidental over-claiming from ephemeral internals.
