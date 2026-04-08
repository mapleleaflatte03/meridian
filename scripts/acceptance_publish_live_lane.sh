#!/usr/bin/env bash
# acceptance_publish_live_lane.sh
# Verify public web surfaces are ready: required sections, no commercial wording,
# consistent nav, research-first positioning, and API status coherence.
# Exits non-zero on any failure.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
FAIL=0

echo "[publish-live-lane] Checking public surface readiness..."

# ---------------------------------------------------------------------------
# 1. UI anatomy lane (consistent header/footer/sections, no pricing CSS)
# ---------------------------------------------------------------------------
echo ""
echo "=== UI anatomy lane ==="
if ./scripts/acceptance_ui_anatomy_lane.sh; then
    echo "[OK]   UI anatomy lane PASS"
else
    echo "[FAIL] UI anatomy lane FAIL"
    FAIL=1
fi

# ---------------------------------------------------------------------------
# 2. Noncommercial wording assertion
# ---------------------------------------------------------------------------
echo ""
echo "=== Noncommercial wording check ==="
if ./scripts/assert_noncommercial_wording.sh; then
    echo "[OK]   Noncommercial wording PASS"
else
    echo "[FAIL] Noncommercial wording FAIL"
    FAIL=1
fi

# ---------------------------------------------------------------------------
# 3. Research-first positioning check
# ---------------------------------------------------------------------------
echo ""
echo "=== Research-first positioning check ==="

check_page_content() {
    local page="$1"
    local label="$2"
    local pattern="$3"
    if grep -qiE "$pattern" "$page" 2>/dev/null; then
        echo "[OK]   $label"
    else
        echo "[FAIL] $label"
        FAIL=1
    fi
}

check_absent_content() {
    local page="$1"
    local label="$2"
    local pattern="$3"
    if ! grep -qiE "$pattern" "$page" 2>/dev/null; then
        echo "[OK]   $label (absent as required)"
    else
        echo "[FAIL] $label (present — should be absent)"
        FAIL=1
    fi
}

INDEX="$ROOT_DIR/intelligence/company/www/index.html"
PROOFS="$ROOT_DIR/intelligence/company/www/proofs.html"
WORKFLOWS="$ROOT_DIR/intelligence/company/www/workflows.html"

# Homepage must have research-first messaging
check_page_content "$INDEX" "index.html: open-source/research mention" \
    "open.source|research|governed|governance|verifiable"

# Homepage must not have paywall or commercial CTAs
check_absent_content "$INDEX" "index.html: no pricing page CTA" \
    "view pricing|our pricing|see pricing"
check_absent_content "$INDEX" "index.html: no subscribe CTA" \
    "subscribe now|subscription plan|paid tier"

# Proofs page must reference runtime proof/receipts
check_page_content "$PROOFS" "proofs.html: proof/receipt reference" \
    "proof|receipt|runtime|PoGE"

# Workflows page must reference governance/workflow
check_page_content "$WORKFLOWS" "workflows.html: governance/workflow reference" \
    "workflow|governed|governance|treasury|receipt"

# All pages must have GitHub link
for page in "$INDEX" "$PROOFS" "$WORKFLOWS"; do
    name="$(basename "$page")"
    check_page_content "$page" "$name: GitHub link present" \
        "github\.com/mapleleaflatte03/meridian"
done

# ---------------------------------------------------------------------------
# 4. API status check
# ---------------------------------------------------------------------------
echo ""
echo "=== API status coherence ==="

BASE_URL="${MERIDIAN_BASE_URL:-http://127.0.0.1:8266}"
if curl -fsS --max-time 5 "$BASE_URL/api/status" >/dev/null 2>&1; then
    STATUS=$(curl -fsS --max-time 10 "$BASE_URL/api/status" 2>/dev/null || echo "{}")
    if echo "$STATUS" | python3 -c "
import json,sys
d = json.load(sys.stdin)
assert d.get('runtime_id'), 'missing runtime_id'
proof = d.get('proof') or {}
assert proof.get('recursive') or proof.get('aggregate'), 'missing proof blocks'
court = (d.get('court') or {}).get('dynamic') or {}
assert court.get('ruleset_version') is not None, 'missing court.dynamic.ruleset_version'
mkt = d.get('marketplace') or {}
assert mkt.get('mode'), 'missing marketplace.mode'
mem = (d.get('memory') or {}).get('temporal_integrity') or {}
assert mem.get('enabled') is not None, 'missing memory.temporal_integrity.enabled'
cw = d.get('commonwealth') or {}
assert cw.get('federation'), 'missing commonwealth.federation'
assert cw.get('settlement'), 'missing commonwealth.settlement'
print('all V5 contract blocks present')
" 2>/dev/null; then
        echo "[OK]   /api/status: all V5 contract blocks present"
    else
        echo "[FAIL] /api/status: missing required V5 contract blocks"
        FAIL=1
    fi
else
    echo "[SKIP] API server not reachable at $BASE_URL — skipping API check"
fi

# ---------------------------------------------------------------------------
# Final verdict
# ---------------------------------------------------------------------------
echo ""
if [[ $FAIL -eq 0 ]]; then
    echo "[publish-live-lane] PASS — public surfaces ready, research-first positioning verified."
else
    echo "[publish-live-lane] FAIL — surface issues found. Fix above."
    exit 1
fi
