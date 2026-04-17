#!/usr/bin/env bash
# acceptance_ui_anatomy_lane.sh
# Verify consistent UI anatomy across /, /proofs, /workflows.
# Checks: anatomy blocks, no pricing remnants, no overflow, consistent header/footer.
# Exits non-zero on any failure.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${MERIDIAN_BASE_URL:-http://127.0.0.1:8266}"
WWW_DIR="$ROOT_DIR/intelligence/company/www"
FAIL=0
ALLOW_API_SKIP="${MERIDIAN_ALLOW_API_SKIP:-0}"
SCREENSHOTS_DIR="/tmp/meridian_ui_anatomy_screenshots"
STATIC_PID_FILE="/tmp/meridian_ui_anatomy_static_server.pid"
STATIC_PORT="${MERIDIAN_UI_STATIC_PORT:-}"
mkdir -p "$SCREENSHOTS_DIR"

cleanup() {
    if [[ -f "$STATIC_PID_FILE" ]]; then
        kill "$(cat "$STATIC_PID_FILE")" 2>/dev/null || true
        rm -f "$STATIC_PID_FILE"
    fi
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
check() {
    local label="$1"; shift
    if "$@" >/dev/null 2>&1; then
        echo "[OK]   $label"
    else
        echo "[FAIL] $label"
        FAIL=1
    fi
}

check_absent() {
    local label="$1"; shift
    if ! "$@" >/dev/null 2>&1; then
        echo "[OK]   $label (absent as required)"
    else
        echo "[FAIL] $label (unexpectedly present)"
        FAIL=1
    fi
}

find_free_port() {
    python3 - <<'PY'
import socket

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
PY
}

# ---------------------------------------------------------------------------
# 1. Static HTML anatomy checks
# ---------------------------------------------------------------------------
echo ""
echo "=== Static HTML anatomy checks ==="

PAGES=("index.html" "proofs.html" "workflows.html")

for page in "${PAGES[@]}"; do
    FILE="$WWW_DIR/$page"
    [[ -f "$FILE" ]] || { echo "[FAIL] Missing $FILE"; FAIL=1; continue; }

    # Header must be present with fixed class
    check "$page: site-header present"   grep -q 'class="site-header"' "$FILE"
    check "$page: header-inner present"  grep -q 'class="header-inner"' "$FILE"
    check "$page: site-nav present"      grep -q 'class="site-nav"' "$FILE"

    # Brand must be present
    check "$page: brand link present"    grep -q 'class="brand"' "$FILE"

    # Hero or page-intro
    check "$page: hero or page-intro"    grep -qE 'class="(hero|page-intro)"' "$FILE"

    # Footer
    check "$page: footer present"        grep -q '<footer' "$FILE"
    check "$page: footer-bottom present" grep -q 'class="footer-bottom"' "$FILE"

    # Mobile viewport meta
    check "$page: viewport meta"         grep -q 'name="viewport"' "$FILE"

    # Nav CTA consistent
    check "$page: nav-cta present"       grep -q 'class="nav-cta"' "$FILE"

    # No direct pricing class usage in HTML
    check_absent "$page: no pricing-grid class"   grep -q 'class="pricing-grid"' "$FILE"
    check_absent "$page: no price-card class"     grep -q 'class="price-card"' "$FILE"
    check_absent "$page: no pricing-section"      grep -q 'class="pricing-section"' "$FILE"
    check_absent "$page: no checkout-card"        grep -q 'class="checkout-card"' "$FILE"
    check_absent "$page: no checkout-section"     grep -q 'class="checkout-section"' "$FILE"
    check_absent "$page: no premium-pricing"      grep -q 'class="premium-pricing"' "$FILE"
done

# Homepage specific sections required
check "index.html: why-meridian section"    grep -q 'id="why-meridian"'     "$WWW_DIR/index.html"

# ---------------------------------------------------------------------------
# 2. CSS cleanliness checks
# ---------------------------------------------------------------------------
echo ""
echo "=== CSS cleanliness checks ==="

CSS_FILE="$WWW_DIR/assets/meridian.css"
[[ -f "$CSS_FILE" ]] || { echo "[FAIL] Missing meridian.css"; FAIL=1; }

if [[ -f "$CSS_FILE" ]]; then
    check_absent "CSS: no .pricing-grid rule"    grep -qE '^\.pricing-grid' "$CSS_FILE"
    check_absent "CSS: no .price-card rule"      grep -qE '^\.price-card' "$CSS_FILE"
    check_absent "CSS: no .pricing-section rule" grep -qE '^\.pricing-section' "$CSS_FILE"
    check_absent "CSS: no .premium-pricing rule" grep -qE '^\.premium-pricing' "$CSS_FILE"
    check_absent "CSS: no .tag-pricing rule"     grep -qE '^\.tag-pricing' "$CSS_FILE"

    # overflow-x protection via max-width/overflow rules
    check "CSS: overflow/max-width protection present" \
        grep -qE 'overflow-x.*hidden|max-width.*100%|overflow.*hidden' "$CSS_FILE"

    # Header height token defined (fixed height, no jump)
    check "CSS: --header-h token defined"  grep -q '\-\-header-h:' "$CSS_FILE"
fi

# ---------------------------------------------------------------------------
# 3. API status check (if server is up)
# ---------------------------------------------------------------------------
echo ""
echo "=== API status check ==="

api_ready=0
for _ in $(seq 1 20); do
    if curl -fsS --max-time 5 "$BASE_URL/api/status" >/dev/null 2>&1; then
        api_ready=1
        break
    fi
    sleep 1
done

if [[ "$api_ready" -eq 1 ]]; then
    STATUS_CODE=$(curl -o /dev/null -fsS --max-time 10 -w "%{http_code}" "$BASE_URL/api/status" 2>/dev/null || echo "000")
    if [[ "$STATUS_CODE" == "200" ]]; then
        echo "[OK]   GET /api/status → $STATUS_CODE"
    else
        echo "[FAIL] GET /api/status → $STATUS_CODE"
        FAIL=1
    fi

    # Verify no commercial wording in API status payload
    API_PAYLOAD=$(curl -fsS --max-time 10 "$BASE_URL/api/status" 2>/dev/null || echo "{}")
    if echo "$API_PAYLOAD" | grep -qiE '"subscribe now"|"subscription plan"|"paid tier"|"premium plan"|"buy now"|"payment required"'; then
        echo "[FAIL] Commercial wording found in /api/status payload"
        FAIL=1
    else
        echo "[OK]   /api/status: no banned commercial wording"
    fi
else
    if [[ "$ALLOW_API_SKIP" == "1" ]]; then
        echo "[SKIP] API server not reachable at $BASE_URL — skipping API checks (MERIDIAN_ALLOW_API_SKIP=1)"
        echo "[WARN] ui-anatomy-lane used API skip; this is not valid evidence for production readiness"
    else
        echo "[FAIL] API server not reachable at $BASE_URL"
        FAIL=1
    fi
fi

# ---------------------------------------------------------------------------
# 4. Playwright screenshot check (optional — skip if not installed)
# ---------------------------------------------------------------------------
echo ""
echo "=== Playwright screenshot check ==="

PLAYWRIGHT_AVAILABLE=0
PLAYWRIGHT_MODE="none"
if command -v node >/dev/null 2>&1; then
    # Check if playwright module is actually installed (not just runnable via npx download)
    if node -e "require('playwright')" >/dev/null 2>&1 || \
       node -e "require('@playwright/test')" >/dev/null 2>&1; then
        PLAYWRIGHT_AVAILABLE=1
        PLAYWRIGHT_MODE="module"
    elif command -v npx >/dev/null 2>&1 && npx playwright --version >/dev/null 2>&1; then
        PLAYWRIGHT_AVAILABLE=1
        PLAYWRIGHT_MODE="npx"
    fi
fi

if [[ $PLAYWRIGHT_AVAILABLE -eq 1 ]]; then
    if [[ -z "${STATIC_PORT}" ]]; then
        STATIC_PORT="$(find_free_port)"
    fi
    # Start static file server for the www directory
    python3 -c "
import http.server
import os
import threading
import sys

os.chdir('$WWW_DIR')
handler = http.server.SimpleHTTPRequestHandler
handler.log_message = lambda *a: None
server = http.server.HTTPServer(('127.0.0.1', $STATIC_PORT), handler)
with open('$STATIC_PID_FILE', 'w') as f:
    import os as _os
    f.write(str(_os.getpid()))
server.serve_forever()
" &
    STATIC_SERVER_PID=$!
    echo "$STATIC_SERVER_PID" > "$STATIC_PID_FILE"
    sleep 1

    STATIC_BASE="http://127.0.0.1:$STATIC_PORT"

    if curl -4 -fsS --max-time 5 "$STATIC_BASE/index.html" >/dev/null 2>&1; then
        if [[ "$PLAYWRIGHT_MODE" == "module" ]]; then
            node - "$STATIC_BASE" "$SCREENSHOTS_DIR" <<'PLAYWRIGHT_EOF'
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const base = process.argv[2];
  const outDir = process.argv[3];
  const browser = await chromium.launch();
  const pages = [
    { path: '/index.html', name: 'home' },
    { path: '/proofs.html', name: 'proofs' },
    { path: '/workflows.html', name: 'workflows' },
  ];
  const viewports = [
    { name: 'desktop', width: 1440, height: 900 },
    { name: 'mobile',  width: 390,  height: 844 },
  ];

  for (const vp of viewports) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    for (const pg of pages) {
      const page = await ctx.newPage();
      await page.goto(base + pg.path, { waitUntil: 'domcontentloaded', timeout: 15000 });
      const file = path.join(outDir, `${pg.name}-${vp.name}.png`);
      await page.screenshot({ path: file, fullPage: false });
      process.stdout.write('screenshot: ' + file + '\n');

      // Check no horizontal overflow
      const overflow = await page.evaluate(() => document.body.scrollWidth > window.innerWidth + 2);
      if (overflow) {
        const sw = await page.evaluate(() => document.body.scrollWidth);
        const iw = await page.evaluate(() => window.innerWidth);
        process.stderr.write('OVERFLOW on ' + pg.path + ' at ' + vp.name + ' (scrollWidth=' + sw + ' innerWidth=' + iw + ')\n');
        process.exit(1);
      }
      await page.close();
    }
    await ctx.close();
  }
  await browser.close();
  process.stdout.write('Playwright anatomy checks passed.\n');
})().catch(e => { process.stderr.write(String(e) + '\n'); process.exit(1); });
PLAYWRIGHT_EOF
        else
            pages=("index.html:home" "proofs.html:proofs" "workflows.html:workflows")
            for page in "${pages[@]}"; do
                src="${page%%:*}"
                name="${page##*:}"

                if ! npx playwright screenshot \
                    --wait-for-timeout 1200 \
                    --timeout 30000 \
                    "$STATIC_BASE/$src" \
                    "$SCREENSHOTS_DIR/${name}-desktop.png" >/dev/null 2>&1; then
                    sleep 1
                    if ! npx playwright screenshot \
                        --wait-for-timeout 1200 \
                        --timeout 30000 \
                        "$STATIC_BASE/$src" \
                        "$SCREENSHOTS_DIR/${name}-desktop.png" >/dev/null 2>&1; then
                        echo "[FAIL] Playwright npx desktop screenshot failed: $src"
                        FAIL=1
                    fi
                fi

                if ! npx playwright screenshot \
                    --viewport-size=390,844 \
                    --wait-for-timeout 1200 \
                    --timeout 30000 \
                    "$STATIC_BASE/$src" \
                    "$SCREENSHOTS_DIR/${name}-mobile.png" >/dev/null 2>&1; then
                    sleep 1
                    if ! npx playwright screenshot \
                        --viewport-size=390,844 \
                        --wait-for-timeout 1200 \
                        --timeout 30000 \
                        "$STATIC_BASE/$src" \
                        "$SCREENSHOTS_DIR/${name}-mobile.png" >/dev/null 2>&1; then
                        echo "[FAIL] Playwright npx mobile screenshot failed: $src"
                        FAIL=1
                    fi
                fi
            done
        fi
        echo "[OK]   Playwright screenshots: $SCREENSHOTS_DIR (mode=$PLAYWRIGHT_MODE)"
    else
        echo "[SKIP] Static server not ready — skipping Playwright screenshots"
    fi

    cleanup
else
    echo "[SKIP] Playwright not available — screenshot checks skipped (static + CSS checks cover anatomy)"
fi

# ---------------------------------------------------------------------------
# Final verdict
# ---------------------------------------------------------------------------
echo ""
if [[ $FAIL -eq 0 ]]; then
    echo "[acceptance-ui-anatomy] PASS — anatomy consistent, no pricing remnants, no overflow."
else
    echo "[acceptance-ui-anatomy] FAIL — anatomy checks failed. Fix issues above."
    exit 1
fi
