#!/usr/bin/env bash
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "[mirror-policy] gh CLI is required"
  exit 1
fi

OWNER_REPO_PREFIX="${OWNER_REPO_PREFIX:-mapleleaflatte03}"
CANONICAL_URL="${CANONICAL_URL:-https://github.com/mapleleaflatte03/meridian}"

MIRRORS=(
  "${OWNER_REPO_PREFIX}/meridian-loom"
  "${OWNER_REPO_PREFIX}/meridian-kernel"
  "${OWNER_REPO_PREFIX}/meridian-intelligence"
)

for repo in "${MIRRORS[@]}"; do
  payload="$(gh repo view "${repo}" --json isArchived,description,homepageUrl)"
  python3 - "${repo}" "${CANONICAL_URL}" "${payload}" <<'PY'
import json
import sys

repo = sys.argv[1]
canonical = sys.argv[2]
payload = json.loads(sys.argv[3])

assert payload.get("isArchived") is True, f"{repo}: isArchived is not true"
homepage = (payload.get("homepageUrl") or "").strip()
assert homepage == canonical, f"{repo}: homepageUrl mismatch: {homepage}"

desc = (payload.get("description") or "").strip().lower()
assert ("archived" in desc) or ("mirror - read only" in desc), f"{repo}: description is not explicit mirror/archive text"
print(f"[mirror-policy] {repo}: PASS")
PY
done

echo "[mirror-policy] PASS"
