#!/usr/bin/env bash
# benchmark-vs-claw.sh — Run the benchmark lane with comparison targets
#
# Run from monorepo root: bash examples/benchmark-vs-claw.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Meridian Benchmark vs Claw-Family Example ==="
echo ""
echo "This runs the reproducible benchmark lane against any detected"
echo "Claw-family CLIs (claude, codex, aider, goose) on this machine."
echo ""

"${ROOT_DIR}/scripts/benchmark_meridian.sh" --with-comparisons --iterations 3

echo ""
echo "=== Benchmark complete ==="
echo "Artifact saved to: runtime/benchmark_artifact.json"
echo "See docs/MIGRATION_FROM_CLAW.md for migration context."
