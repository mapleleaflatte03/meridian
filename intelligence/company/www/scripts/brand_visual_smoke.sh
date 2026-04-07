#!/usr/bin/env bash
set -euo pipefail

SITE_ROOT="${SITE_ROOT:-https://app.welliam.codes}"
OUTPUT_DIR="${OUTPUT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/artifacts/brand-snapshots}"

mkdir -p "${OUTPUT_DIR}"

echo "[brand-smoke] ensuring Playwright Chromium is installed"
npx --yes playwright install chromium >/dev/null

capture() {
  local url="$1"
  local out="$2"
  shift 2
  npx --yes playwright screenshot "$@" "${url}" "${out}"
}

echo "[brand-smoke] output_dir=${OUTPUT_DIR}"
capture "${SITE_ROOT}/" "${OUTPUT_DIR}/index-desktop.png" --browser chromium --viewport-size "1440,900" --wait-for-timeout 1200
capture "${SITE_ROOT}/demo" "${OUTPUT_DIR}/demo-desktop.png" --browser chromium --viewport-size "1440,900" --wait-for-timeout 1200
capture "${SITE_ROOT}/compare" "${OUTPUT_DIR}/compare-desktop.png" --browser chromium --viewport-size "1440,900" --wait-for-timeout 1200

capture "${SITE_ROOT}/" "${OUTPUT_DIR}/index-mobile.png" --browser chromium --viewport-size "390,844" --wait-for-timeout 1200
capture "${SITE_ROOT}/demo" "${OUTPUT_DIR}/demo-mobile.png" --browser chromium --viewport-size "390,844" --wait-for-timeout 1200
capture "${SITE_ROOT}/compare" "${OUTPUT_DIR}/compare-mobile.png" --browser chromium --viewport-size "390,844" --wait-for-timeout 1200

echo "[brand-smoke] PASS snapshots written:"
ls -1 "${OUTPUT_DIR}"/*.png
