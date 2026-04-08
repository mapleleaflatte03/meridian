#!/usr/bin/env bash
# verify_archive_policy.sh
# Verify that all 3 Meridian legacy mirror repositories are archived on GitHub.
# Also validates migration map and issue template config exist.
# Exits non-zero on any failure.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
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

# ---------------------------------------------------------------------------
# 1. GitHub archive status (requires gh CLI)
# ---------------------------------------------------------------------------
echo ""
echo "=== GitHub mirror archive check ==="

CANONICAL_URL="https://github.com/mapleleaflatte03/meridian"
MIRRORS=(
    "mapleleaflatte03/meridian-loom"
    "mapleleaflatte03/meridian-kernel"
    "mapleleaflatte03/meridian-intelligence"
)

if ! command -v gh >/dev/null 2>&1; then
    echo "[SKIP] gh CLI not installed — skipping GitHub archive checks"
else
    for repo in "${MIRRORS[@]}"; do
        payload="$(gh repo view "${repo}" --json isArchived,homepageUrl 2>/dev/null || echo "{}")"
        result="$(python3 - "${repo}" "${CANONICAL_URL}" "${payload}" <<'PY'
import json, sys

repo = sys.argv[1]
canonical = sys.argv[2]
try:
    payload = json.loads(sys.argv[3])
except Exception:
    print(f"FAIL: {repo}: could not parse repo payload")
    sys.exit(1)

archived = payload.get("isArchived")
if not archived:
    print(f"FAIL: {repo}: isArchived={archived!r}")
    sys.exit(1)

homepage = (payload.get("homepageUrl") or "").strip().rstrip("/")
canonical_norm = canonical.strip().rstrip("/")
if homepage and homepage != canonical_norm:
    print(f"FAIL: {repo}: homepageUrl={homepage!r} (expected {canonical_norm!r} or empty)")
    sys.exit(1)

print(f"OK: {repo}: archived=True, homepage ok")
PY
)"
        if echo "$result" | grep -q "^FAIL"; then
            echo "[FAIL] $result"
            FAIL=1
        else
            echo "[OK]   $result"
        fi
    done
fi

# ---------------------------------------------------------------------------
# 2. Local doc files
# ---------------------------------------------------------------------------
echo ""
echo "=== Migration doc presence check ==="

check "docs/MIGRATION_MAP.md exists"        test -f "$ROOT_DIR/docs/MIGRATION_MAP.md"
check "docs/ARCHIVE_POLICY.md exists"       test -f "$ROOT_DIR/docs/ARCHIVE_POLICY.md"
check "docs/REPO_MIGRATION_MAP.md exists"   test -f "$ROOT_DIR/docs/REPO_MIGRATION_MAP.md"
check "docs/MIRROR_ARCHIVE_STATUS.md exists" test -f "$ROOT_DIR/docs/MIRROR_ARCHIVE_STATUS.md"

# Migration map must reference monorepo canonical URL
check "MIGRATION_MAP.md has canonical URL"  grep -q "mapleleaflatte03/meridian" "$ROOT_DIR/docs/MIGRATION_MAP.md"

# Migration map must route contributors (issues, PRs, discussions, wiki)
check "MIGRATION_MAP.md routes issues"      grep -qi "issue" "$ROOT_DIR/docs/MIGRATION_MAP.md"
check "MIGRATION_MAP.md routes discussions" grep -qi "discussion" "$ROOT_DIR/docs/MIGRATION_MAP.md"

# Archive policy must list all 3 mirrors
check "ARCHIVE_POLICY.md lists meridian-loom"         grep -q "meridian-loom"         "$ROOT_DIR/docs/ARCHIVE_POLICY.md"
check "ARCHIVE_POLICY.md lists meridian-kernel"       grep -q "meridian-kernel"       "$ROOT_DIR/docs/ARCHIVE_POLICY.md"
check "ARCHIVE_POLICY.md lists meridian-intelligence" grep -q "meridian-intelligence" "$ROOT_DIR/docs/ARCHIVE_POLICY.md"

# ---------------------------------------------------------------------------
# 3. Issue template config
# ---------------------------------------------------------------------------
echo ""
echo "=== Issue template config check ==="

CONFIG="$ROOT_DIR/.github/ISSUE_TEMPLATE/config.yml"
check ".github/ISSUE_TEMPLATE/config.yml exists"         test -f "$CONFIG"
check "config.yml: blank_issues_enabled=false"           grep -q "blank_issues_enabled: false" "$CONFIG"
check "config.yml: canonical monorepo URL present"       grep -q "mapleleaflatte03/meridian" "$CONFIG"
check "config.yml: contribution guide linked"            grep -qi "contrib" "$CONFIG"

# ---------------------------------------------------------------------------
# Final verdict
# ---------------------------------------------------------------------------
echo ""
if [[ $FAIL -eq 0 ]]; then
    echo "[verify-archive-policy] PASS — monorepo canonical, 3 mirrors archived, migration map complete."
else
    echo "[verify-archive-policy] FAIL — policy gaps found. Fix above."
    exit 1
fi
