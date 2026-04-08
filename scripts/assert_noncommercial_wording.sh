#!/usr/bin/env bash
# assert_noncommercial_wording.sh
# Scan public-facing surfaces for banned commercial/paywall wording.
# Exits non-zero if any banned term is found.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAIL=0

# ---------------------------------------------------------------------------
# Banned term patterns (regex, case-insensitive)
# Match affirmative commercial/paywall prompts — NOT negative disclaimers.
# Each pattern is anchored to NOT match "no ", "without ", "not " prefixes.
# ---------------------------------------------------------------------------
BANNED_PATTERNS=(
    "subscribe now"
    "subscription plan"
    "paid tier"
    "premium plan"
    "buy now"
    "purchase a license"
    "unlock.*feature"
    "upgrade your plan"
    "enterprise pricing"
    "start.*free trial"
    "credit card required"
    "billing plan"
    "checkout.*required"
    "payment required"
)

# These patterns must be checked for affirmative use only (not preceded by negation)
AFFIRMATIVE_ONLY_PATTERNS=(
    "our pricing"
    "view pricing"
    "see pricing"
    "pricing page"
    "pricing plan"
    "pricing tier"
    "sign up.*\\\$[0-9]"
    "requires.*payment"
    "paywall required"
    "gated.*feature"
    "premium.*only"
    "pro.*only"
)

# ---------------------------------------------------------------------------
# Scan targets
# ---------------------------------------------------------------------------
SCAN_TARGETS=(
    "$ROOT_DIR/README.md"
    "$ROOT_DIR/docs/RESEARCH_HUB.md"
    "$ROOT_DIR/docs/research/README.md"
    "$ROOT_DIR/docs/ONBOARDING_CONTRACT.md"
    "$ROOT_DIR/intelligence/company/www/index.html"
    "$ROOT_DIR/intelligence/company/www/proofs.html"
    "$ROOT_DIR/intelligence/company/www/workflows.html"
)

# Also scan any HTML pages that exist
for html_file in "$ROOT_DIR"/intelligence/company/www/*.html; do
    [[ -f "$html_file" ]] || continue
    # Avoid duplicates already in SCAN_TARGETS
    already=0
    for t in "${SCAN_TARGETS[@]}"; do
        [[ "$t" == "$html_file" ]] && { already=1; break; }
    done
    [[ $already -eq 0 ]] && SCAN_TARGETS+=("$html_file")
done

# ---------------------------------------------------------------------------
# Also probe /api/status payload if server is reachable
# ---------------------------------------------------------------------------
BASE_URL="${MERIDIAN_BASE_URL:-http://127.0.0.1:8266}"
API_PAYLOAD_FILE="/tmp/_assert_noncommercial_api_status.txt"
if curl -fsS --max-time 5 "$BASE_URL/api/status" -o "$API_PAYLOAD_FILE" 2>/dev/null; then
    SCAN_TARGETS+=("$API_PAYLOAD_FILE")
fi

# ---------------------------------------------------------------------------
# Scan loop
# ---------------------------------------------------------------------------
echo "[assert-noncommercial] Scanning ${#SCAN_TARGETS[@]} targets..."

for target in "${SCAN_TARGETS[@]}"; do
    [[ -f "$target" ]] || continue
    for pattern in "${BANNED_PATTERNS[@]}"; do
        if grep -qiE "$pattern" "$target" 2>/dev/null; then
            echo "[FAIL] Banned term '$pattern' found in: $target"
            grep -niE "$pattern" "$target" | head -3
            FAIL=1
        fi
    done
    for pattern in "${AFFIRMATIVE_ONLY_PATTERNS[@]}"; do
        # Only flag if NOT preceded within the same line by no/without/not/never
        if grep -iE "$pattern" "$target" 2>/dev/null | grep -qivE "(^|\s)(no|without|not|never)\s"; then
            # Check if the pattern line exists and is NOT a negation
            if grep -niE "$pattern" "$target" 2>/dev/null | grep -ivE "(no |without |not |never )" | grep -q .; then
                echo "[FAIL] Affirmative commercial term '$pattern' found in: $target"
                grep -niE "$pattern" "$target" | grep -ivE "(no |without |not |never )" | head -3
                FAIL=1
            fi
        fi
    done
done

if [[ $FAIL -eq 0 ]]; then
    echo "[assert-noncommercial] PASS — no banned commercial wording found."
else
    echo "[assert-noncommercial] FAIL — banned commercial wording detected. Fix before proceeding."
    exit 1
fi
