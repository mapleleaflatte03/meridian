#!/usr/bin/env bash
# acceptance_commonwealth_ui_lane.sh
# Verifies commonwealth API surfaces are accessible and return valid JSON.
# Uses Playwright for screenshot checks if installed; otherwise static checks only.
set -euo pipefail

BASE_URL="${MERIDIAN_BASE_URL:-http://127.0.0.1:8266}"
FAIL=0

pass() { echo "[OK]   $1"; }
fail() { echo "[FAIL] $1"; FAIL=1; }
skip() { echo "[SKIP] $1"; }

echo "=== Commonwealth UI / Surface Verification ==="

# ── API surface checks ───────────────────────────────────────────────────────
echo ""
echo "--- API Surface Reachability ---"

check_api() {
    local label="$1"
    local path="$2"
    local field="$3"
    local resp
    resp="$(curl -fsS --max-time 10 "$BASE_URL$path" 2>/dev/null || echo "")"
    if [[ -z "$resp" ]]; then
        fail "$label: no response from $path"
        return
    fi
    if echo "$resp" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); assert d.get('$field') is not None" 2>/dev/null; then
        pass "$label"
    else
        fail "$label: field '$field' missing in response"
    fi
}

check_api "GET /api/commonwealth/federation: protocol_version" "/api/commonwealth/federation" "protocol_version"
check_api "GET /api/commonwealth/memory/anchor: anchor_status" "/api/commonwealth/memory/anchor" "anchor_status"
check_api "GET /api/commonwealth/proof-bundle: protocol" "/api/commonwealth/proof-bundle" "protocol"

# ── /api/status commonwealth blocks ──────────────────────────────────────────
echo ""
echo "--- /api/status Commonwealth Blocks ---"

STATUS_RESP="$(curl -fsS --max-time 10 "$BASE_URL/api/status" 2>/dev/null || echo "{}")"
echo "$STATUS_RESP" > /tmp/cw_ui_status.json

python3 - /tmp/cw_ui_status.json <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
cw = d.get('commonwealth', {})
blocks = {
    'commonwealth.federation': cw.get('federation'),
    'commonwealth.settlement': cw.get('settlement'),
}
ok = True
for name, val in blocks.items():
    if val is not None:
        print(f'[OK]   /api/status: {name} present')
    else:
        print(f'[FAIL] /api/status: {name} missing')
        ok = False
sys.exit(0 if ok else 1)
PY
if [[ $? -ne 0 ]]; then FAIL=1; fi

# ── Playwright screenshot check (optional) ───────────────────────────────────
echo ""
echo "--- Playwright Screenshots (optional) ---"

HAS_PLAYWRIGHT=false
if node -e "require('playwright')" 2>/dev/null; then
    HAS_PLAYWRIGHT=true
fi

if $HAS_PLAYWRIGHT; then
    SCREENSHOT_DIR="/tmp/commonwealth_ui_screenshots"
    mkdir -p "$SCREENSHOT_DIR"
    node - "$BASE_URL" "$SCREENSHOT_DIR" <<'JS'
const { chromium } = require('playwright');
(async () => {
    const base = process.argv[2];
    const dir = process.argv[3];
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

    // Check main page loads
    await page.goto(base + '/api/status', { waitUntil: 'networkidle', timeout: 15000 });
    await page.screenshot({ path: dir + '/api_status.png', fullPage: true });

    // Check commonwealth federation API
    await page.goto(base + '/api/commonwealth/federation', { waitUntil: 'networkidle', timeout: 15000 });
    await page.screenshot({ path: dir + '/cw_federation.png', fullPage: true });

    // Check commonwealth memory anchor
    await page.goto(base + '/api/commonwealth/memory/anchor', { waitUntil: 'networkidle', timeout: 15000 });
    await page.screenshot({ path: dir + '/cw_memory_anchor.png', fullPage: true });

    await browser.close();
    console.log('Screenshots saved to ' + dir);
})().catch(err => { console.error(err.message); process.exit(1); });
JS
    if [[ $? -eq 0 ]]; then
        pass "Playwright commonwealth screenshots captured"
    else
        fail "Playwright screenshot capture failed"
    fi
else
    skip "Playwright not installed — skipping browser screenshots"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
if [[ $FAIL -eq 0 ]]; then
    echo "[acceptance_commonwealth_ui_lane] PASS"
else
    echo "[acceptance_commonwealth_ui_lane] FAIL"
    exit 1
fi
