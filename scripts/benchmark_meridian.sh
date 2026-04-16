#!/usr/bin/env bash
# benchmark_meridian.sh — Reproducible benchmark lane for Meridian
#
# Measures cold-start time, peak RSS, proof-route availability, and
# policy-gated execution overhead for Meridian and (optionally) comparison
# targets on the same machine.
#
# Usage:
#   ./scripts/benchmark_meridian.sh                    # Meridian only
#   ./scripts/benchmark_meridian.sh --with-comparisons # include detected rivals
#   ./scripts/benchmark_meridian.sh --json             # JSON output
#   ./scripts/benchmark_meridian.sh --iterations 10    # custom iteration count
#
# Output:
#   Markdown table to stdout (default) or JSON.
#   Artifact written to runtime/benchmark_artifact.json.
#
# Caveats:
#   - This is a bounded local benchmark, not a lab-grade evaluation.
#   - Competitor binaries must be installed on the same machine to be included.
#   - RSS sampling depends on /proc (Linux) or ps (macOS).
#   - Results are machine-specific and should not be cited as universal.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOOM_BIN="${ROOT_DIR}/loom/target/release/loom"
BENCH_SCRIPT="${ROOT_DIR}/loom/scripts/bench_runtime.py"
ARTIFACT_DIR="${ROOT_DIR}/runtime"
ARTIFACT_PATH="${ARTIFACT_DIR}/benchmark_artifact.json"

WITH_COMPARISONS=false
FORMAT="markdown"
ITERATIONS=5

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-comparisons) WITH_COMPARISONS=true; shift ;;
    --json) FORMAT="json"; shift ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

echo "=================================="
echo "  Meridian Benchmark Lane"
echo "=================================="
echo ""
echo "  Iterations: $ITERATIONS"
echo "  Format: $FORMAT"
echo "  Comparisons: $WITH_COMPARISONS"
echo ""

# ── Build case list ────────────────────────────────────────────────────────

CASES=()

# Meridian Loom status (cold start)
if [ -x "$LOOM_BIN" ]; then
  CASES+=("--case" "loom-status::${LOOM_BIN} status --root ${ROOT_DIR}/runtime/default 2>/dev/null || true")
  CASES+=("--case" "loom-help::${LOOM_BIN} --help")
else
  echo "[warn] Loom binary not found at $LOOM_BIN — skipping Loom cases."
fi

# Meridian core.sh inspect (Core path cold start)
if [ -x "${ROOT_DIR}/scripts/core.sh" ]; then
  CASES+=("--case" "core-inspect::bash ${ROOT_DIR}/scripts/core.sh inspect 2>/dev/null || true")
fi

# ── Comparison targets (only if --with-comparisons) ────────────────────────

if [ "$WITH_COMPARISONS" = true ]; then
  # OpenClaw / claude-code
  if command -v claude >/dev/null 2>&1; then
    CASES+=("--case" "claude-help::claude --help")
  else
    echo "[info] claude not found — skipping OpenClaw comparison."
  fi

  # OpenFang / codex
  if command -v codex >/dev/null 2>&1; then
    CASES+=("--case" "codex-help::codex --help")
  else
    echo "[info] codex not found — skipping OpenFang comparison."
  fi

  # ZeroClaw / aider
  if command -v aider >/dev/null 2>&1; then
    CASES+=("--case" "aider-help::aider --help")
  else
    echo "[info] aider not found — skipping ZeroClaw comparison."
  fi

  # Goose
  if command -v goose >/dev/null 2>&1; then
    CASES+=("--case" "goose-help::goose --help")
  else
    echo "[info] goose not found — skipping Goose comparison."
  fi
fi

if [ ${#CASES[@]} -eq 0 ]; then
  echo "[error] No benchmark cases available. Ensure loom binary is built."
  exit 1
fi

# ── Run benchmark ──────────────────────────────────────────────────────────

echo "Running benchmark..."
echo ""

mkdir -p "$ARTIFACT_DIR"

# Always produce JSON artifact
python3 "$BENCH_SCRIPT" \
  "${CASES[@]}" \
  --iterations "$ITERATIONS" \
  --warmup 1 \
  --format json \
  > "$ARTIFACT_PATH"

echo "[artifact] Written to: $ARTIFACT_PATH"
echo ""

# ── Proof-route availability check ────────────────────────────────────────

echo "--- Proof Route Availability ---"
PROOF_ROUTES=(
  "/api/status"
  "/api/runtime-proof"
  "/api/kernel-proof-bundle"
  "/api/institution/template"
  "/api/treasury"
)

GATEWAY_UP=false
if curl -fsS "http://127.0.0.1:8266/api/status" >/dev/null 2>&1; then
  GATEWAY_UP=true
fi

for route in "${PROOF_ROUTES[@]}"; do
  if [ "$GATEWAY_UP" = true ]; then
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8266${route}" 2>/dev/null || echo "err")
    echo "  ${route}: ${STATUS}"
  else
    echo "  ${route}: gateway not running (expected in offline benchmark)"
  fi
done
echo ""

# ── Display results ────────────────────────────────────────────────────────

if [ "$FORMAT" = "json" ]; then
  cat "$ARTIFACT_PATH"
else
  python3 "$BENCH_SCRIPT" \
    "${CASES[@]}" \
    --iterations "$ITERATIONS" \
    --warmup 0 \
    --format markdown
fi

echo ""
echo "--- Caveats ---"
echo "  - Machine-specific results; do not cite as universal benchmarks."
echo "  - Cold-start measures CLI invocation only, not full agent loop latency."
echo "  - RSS sampling is approximate (poll-based, not kernel-precise)."
echo "  - Competitor binaries must be locally installed to be included."
echo "  - Run with --with-comparisons to include detected rival CLIs."
echo ""
echo "[benchmark] Done."
