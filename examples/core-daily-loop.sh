#!/usr/bin/env bash
# core-daily-loop.sh — Demonstrate the Meridian Core daily task loop
#
# Run after onboarding: bash examples/core-daily-loop.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="${ROOT_DIR}/scripts/core.sh"

echo "=== Meridian Core Daily Loop Example ==="
echo ""

echo "1. Browse a URL..."
"$CORE" browse https://example.com 2>/dev/null || echo "   (browse completed or skipped)"
echo ""

echo "2. Run a research command..."
"$CORE" research "echo 'Hello from Meridian Core'" 2>/dev/null || echo "   (research completed or skipped)"
echo ""

echo "3. Store a memory entry..."
"$CORE" remember demo_note "This is an example memory entry from the daily loop example" 2>/dev/null || echo "   (memory stored or skipped)"
echo ""

echo "4. Recall the memory..."
"$CORE" recall demo_note 2>/dev/null || echo "   (recall completed or skipped)"
echo ""

echo "5. Inspect runtime state..."
"$CORE" inspect 2>/dev/null || echo "   (inspect completed or skipped)"
echo ""

echo "=== Daily loop complete ==="
echo "This demonstrates the Core task runner surface: browse, research, memory, inspect."
echo "No governance expertise required."
