#!/usr/bin/env bash
# core-scheduled-check.sh — Demonstrate Meridian Core scheduled tasks
#
# Run after onboarding: bash examples/core-scheduled-check.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="${ROOT_DIR}/scripts/core.sh"

echo "=== Meridian Core Scheduled Check Example ==="
echo ""

echo "1. Schedule a recurring check (every 3600 seconds)..."
"$CORE" schedule health_check 3600 2>/dev/null || echo "   (schedule created or skipped)"
echo ""

echo "2. List scheduled tasks..."
"$CORE" schedules 2>/dev/null || echo "   (schedules listed or skipped)"
echo ""

echo "3. Check runtime status..."
"$CORE" status 2>/dev/null || echo "   (status shown or skipped)"
echo ""

echo "=== Scheduled check example complete ==="
echo "Meridian Core supports recurring task scheduling without governance overhead."
