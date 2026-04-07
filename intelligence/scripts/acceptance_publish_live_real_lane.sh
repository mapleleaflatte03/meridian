#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAUNCH_DIR="${WORKSPACE_DIR}/company/launch"
ARTIFACT_DIR="${LAUNCH_DIR}/artifacts"

required_env=(
  MERIDIAN_X_API_TOKEN
  MERIDIAN_REDDIT_CLIENT_ID
  MERIDIAN_REDDIT_CLIENT_SECRET
  MERIDIAN_REDDIT_USERNAME
  MERIDIAN_REDDIT_PASSWORD
  MERIDIAN_HN_USERNAME
  MERIDIAN_HN_PASSWORD
  MERIDIAN_DISCORD_WEBHOOK_URL
)

missing=()
for key in "${required_env[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    missing+=("${key}")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "acceptance_publish_live_real_lane: FAIL missing credentials" >&2
  for key in "${missing[@]}"; do
    echo "  - ${key}" >&2
  done
  exit 2
fi

TMP_OUT="$(mktemp /tmp/meridian_publish_live_real.XXXXXX.json)"
trap 'rm -f "${TMP_OUT}"' EXIT

python3 "${LAUNCH_DIR}/publish_live.py" \
  --launch-dir "${LAUNCH_DIR}" \
  --artifact-dir "${ARTIFACT_DIR}" \
  --channels x,reddit,hn,discord \
  --site "https://app.welliam.codes" >"${TMP_OUT}"

python3 - <<'PY' "${TMP_OUT}"
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "ok":
    raise SystemExit(f"publish status is not ok: {payload.get('status')}")

expected = {
    "x": "posted",
    "reddit": "posted",
    "hn": "posted",
    "discord": "posted",
}

results = payload.get("results_by_channel", {})
for channel, expected_status in expected.items():
    channel_payload = results.get(channel, {})
    actual = channel_payload.get("status")
    if actual != expected_status:
        raise SystemExit(
            f"channel {channel} status mismatch: expected={expected_status} actual={actual}"
        )
PY

echo "acceptance_publish_live_real_lane: PASS"
