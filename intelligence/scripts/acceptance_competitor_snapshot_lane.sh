#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_JSON="${ROOT}/output/competitor_snapshot/latest.json"
OUT_MD="${ROOT}/output/competitor_snapshot/latest.md"

"${ROOT}/scripts/collect_competitor_snapshot.py" \
  --out-json "${OUT_JSON}" \
  --out-md "${OUT_MD}"

test -f "${OUT_JSON}" || { echo "missing snapshot json"; exit 1; }
test -f "${OUT_MD}" || { echo "missing snapshot markdown"; exit 1; }

jq -e '.repos | length == 10' "${OUT_JSON}" >/dev/null
jq -e '.repos[] | .commit_velocity.last_72h >= 0' "${OUT_JSON}" >/dev/null

echo "[competitor-snapshot] PASS json=${OUT_JSON} md=${OUT_MD}"
