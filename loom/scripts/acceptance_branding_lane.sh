#!/usr/bin/env bash
set -euo pipefail

WORKSPACE_WWW="${WORKSPACE_WWW:-/home/ubuntu/.meridian/workspace/company/www}"
VERIFY_SCRIPT="${WORKSPACE_WWW}/scripts/verify_brand_contract.py"
SMOKE_SCRIPT="${WORKSPACE_WWW}/scripts/brand_visual_smoke.sh"
SNAPSHOT_DIR="${WORKSPACE_WWW}/artifacts/brand-snapshots"

if [[ ! -f "${VERIFY_SCRIPT}" ]]; then
  echo "missing verifier script: ${VERIFY_SCRIPT}" >&2
  exit 1
fi

if [[ ! -f "${SMOKE_SCRIPT}" ]]; then
  echo "missing visual smoke script: ${SMOKE_SCRIPT}" >&2
  exit 1
fi

echo "[loom-acceptance] verify brand contract"
python3 "${VERIFY_SCRIPT}" --output human

echo "[loom-acceptance] capture brand visual smoke snapshots"
SITE_ROOT="${SITE_ROOT:-https://app.welliam.codes}" OUTPUT_DIR="${SNAPSHOT_DIR}" "${SMOKE_SCRIPT}"

COUNT="$(find "${SNAPSHOT_DIR}" -maxdepth 1 -type f -name '*.png' | wc -l | tr -d ' ')"
if [[ "${COUNT}" -lt 6 ]]; then
  echo "expected at least 6 brand snapshots, found ${COUNT}" >&2
  exit 1
fi

echo "[loom-acceptance] PASS branding lane (${COUNT} snapshots)"
