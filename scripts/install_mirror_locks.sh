#!/usr/bin/env bash
# install_mirror_locks.sh — install active lock markers in archived mirrors.
#
# The archived mirror repositories (meridian-loom, meridian-intelligence,
# meridian-kernel) are kept around for permalink stability but must not
# receive new feature work. ARCHIVE_POLICY.md documents this rule, but
# docs alone don't stop a coding agent from typing `git commit` in the
# wrong tree. This script adds *active* guards:
#
#   1. A MIRROR_LOCK.md marker at repo root with a clear redirect banner.
#   2. A .git/hooks/pre-commit hook that exits non-zero and prints the
#      canonical path any operator should use instead.
#   3. A MIRROR_LOCK.json machine-readable marker so tooling (the
#      verify_canonical_repo.sh --strict mode and downstream scripts)
#      can assert the locks are in place.
#
# Idempotent: safe to re-run. Existing markers are overwritten so the
# canonical path and banner text stay in sync with the monorepo.
#
# Usage:
#   scripts/install_mirror_locks.sh                    # install everywhere
#   scripts/install_mirror_locks.sh --dry-run          # preview only
#   MERIDIAN_MIRROR_PATHS="/path/a:/path/b" install... # custom mirrors
set -u

CANONICAL_PATH="${MERIDIAN_CANONICAL_PATH:-/home/ubuntu/meridian}"
CANONICAL_REMOTE="${MERIDIAN_CANONICAL_REMOTE:-https://github.com/mapleleaflatte03/meridian}"
MIRROR_PATHS_DEFAULT=(
    "/home/ubuntu/meridian-loom:loom"
    "/home/ubuntu/meridian-intelligence:intelligence"
    "/opt/meridian-kernel:kernel"
)
if [ -n "${MERIDIAN_MIRROR_PATHS:-}" ]; then
    IFS=':' read -r -a MIRROR_PATHS <<< "$MERIDIAN_MIRROR_PATHS"
    MAPPED=()
    for p in "${MIRROR_PATHS[@]}"; do
        MAPPED+=("$p:unknown")
    done
    MIRROR_PATHS=("${MAPPED[@]}")
else
    MIRROR_PATHS=("${MIRROR_PATHS_DEFAULT[@]}")
fi

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --help|-h)
            sed -n '2,24p' "$0"
            exit 0
            ;;
        *)
            echo "install_mirror_locks: unknown arg: $arg" >&2
            exit 64
            ;;
    esac
done

say() { printf '%s\n' "$*"; }
indent() { sed 's/^/    /'; }

render_lock_md() {
    local canonical_subpath="$1"
    cat <<EOF
# MIRROR LOCK — READ-ONLY

This repository is an **archived mirror**. It is kept for permalink
stability only. Do not do new feature work here.

**Canonical monorepo:** \`${CANONICAL_PATH}\`
**Canonical remote:**   ${CANONICAL_REMOTE}
**Canonical subpath:**  \`${canonical_subpath}\`

## Why this file exists

A \`pre-commit\` hook in this repo rejects all commits with a redirect
message. \`MIRROR_LOCK.json\` next to this file holds the same info in
machine-readable form so \`verify_canonical_repo.sh --strict\` can
assert the lock is still in place.

See \`ARCHIVE_POLICY.md\` for the full policy.

## If you arrived here intending to change code

Stop. Switch to the canonical monorepo instead:

\`\`\`
cd ${CANONICAL_PATH}
# make your change under: ${canonical_subpath}/
\`\`\`

## Reinstalling the lock

From the canonical monorepo:

\`\`\`
bash scripts/install_mirror_locks.sh
\`\`\`
EOF
}

render_lock_json() {
    local path="$1" subpath="$2"
    python3 - "$path" "$subpath" "$CANONICAL_PATH" "$CANONICAL_REMOTE" <<'PY'
import json, sys, os, time
path, subpath, canonical_path, canonical_remote = sys.argv[1:5]
print(json.dumps({
    "kind": "meridian_mirror_lock",
    "version": 1,
    "mirror_path": path,
    "canonical_path": canonical_path,
    "canonical_remote": canonical_remote,
    "canonical_subpath": subpath,
    "installed_at_unix": int(time.time()),
    "policy": "mirror_is_read_only_new_work_in_canonical",
}, indent=2))
PY
}

render_pre_commit_hook() {
    local canonical_subpath="$1"
    cat <<HOOK
#!/usr/bin/env bash
# Meridian mirror pre-commit lock.
#
# This mirror is archived. New feature work goes in the canonical
# monorepo. To bypass this hook (emergency metadata-only fix), set
# MERIDIAN_MIRROR_ALLOW_COMMIT=1 in your environment.
set -u
if [ "\${MERIDIAN_MIRROR_ALLOW_COMMIT:-0}" = "1" ]; then
    exit 0
fi
cat >&2 <<MSG
[meridian] ✖ Commit refused: this repository is an archived mirror.

  canonical path:   ${CANONICAL_PATH}
  canonical remote: ${CANONICAL_REMOTE}
  canonical subpath: ${canonical_subpath}

  Switch to the canonical monorepo:
    cd ${CANONICAL_PATH}
    # make your change under: ${canonical_subpath}/

  To override for a legitimate mirror sync commit:
    MERIDIAN_MIRROR_ALLOW_COMMIT=1 git commit ...

  See MIRROR_LOCK.md and ARCHIVE_POLICY.md for policy.
MSG
exit 1
HOOK
}

install_one() {
    local entry="$1"
    local path="${entry%%:*}"
    local subpath="${entry#*:}"
    if [ ! -d "$path" ]; then
        say "skip: $path (not present)"
        return 0
    fi
    if [ ! -d "$path/.git" ] && [ ! -f "$path/.git" ]; then
        say "skip: $path (not a git repo)"
        return 0
    fi
    say "lock: $path  →  canonical=${CANONICAL_PATH}/${subpath}"
    if [ "$DRY_RUN" -eq 1 ]; then
        return 0
    fi
    render_lock_md "$subpath" > "$path/MIRROR_LOCK.md"
    render_lock_json "$path" "$subpath" > "$path/MIRROR_LOCK.json"
    # Ignore core.hooksPath settings (like /dev/null) by forcing the config
    # override to default .git/hooks to ensure the hook gets installed in the local repo.
    local git_dir_rel
    git_dir_rel="$(git -C "$path" -c core.hooksPath=.git/hooks rev-parse --git-path hooks 2>/dev/null || echo ".git/hooks")"
    local hooks_dir
    case "$git_dir_rel" in
        /*) hooks_dir="$git_dir_rel" ;;
        *)  hooks_dir="$path/$git_dir_rel" ;;
    esac
    mkdir -p "$hooks_dir"
    render_pre_commit_hook "$subpath" > "$hooks_dir/pre-commit"
    chmod +x "$hooks_dir/pre-commit"
    say "  wrote MIRROR_LOCK.md MIRROR_LOCK.json $hooks_dir/pre-commit"
}

for entry in "${MIRROR_PATHS[@]}"; do
    install_one "$entry"
done

if [ "$DRY_RUN" -eq 1 ]; then
    say "(dry-run; no files were written)"
fi
