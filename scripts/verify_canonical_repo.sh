#!/usr/bin/env bash
# verify_canonical_repo.sh — workspace clarity preflight for Meridian.
#
# Inspects local Meridian repos and reports which is the canonical
# monorepo and which are archived mirrors. Any coding agent landing
# in this workspace should be able to run this to immediately know
# the layout without reading old docs.
#
# Usage:
#   scripts/verify_canonical_repo.sh           # human output
#   scripts/verify_canonical_repo.sh --json    # JSON output
#   scripts/verify_canonical_repo.sh --strict  # exit non-zero if any
#                                              # archived mirror has
#                                              # uncommitted local
#                                              # divergence
set -u

CANONICAL_PATH="${MERIDIAN_CANONICAL_PATH:-/home/ubuntu/meridian}"
MIRROR_PATHS_DEFAULT=(
    "/home/ubuntu/meridian-loom"
    "/home/ubuntu/meridian-intelligence"
    "/opt/meridian-kernel"
)
if [ -n "${MERIDIAN_MIRROR_PATHS:-}" ]; then
    # Allow operators to override the mirror list via colon-separated env.
    IFS=':' read -r -a MIRROR_PATHS <<< "$MERIDIAN_MIRROR_PATHS"
else
    MIRROR_PATHS=("${MIRROR_PATHS_DEFAULT[@]}")
fi

OUTPUT_MODE="human"
STRICT=0
for arg in "$@"; do
    case "$arg" in
        --json) OUTPUT_MODE="json" ;;
        --human) OUTPUT_MODE="human" ;;
        --strict) STRICT=1 ;;
        --help|-h)
            sed -n '2,15p' "$0"
            exit 0
            ;;
        *)
            echo "verify_canonical_repo: unknown arg: $arg" >&2
            exit 64
            ;;
    esac
done

probe_repo() {
    # Args: path role
    local path="$1"
    local role="$2"
    if [ ! -d "$path" ]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$path" "$role" "missing" "" "" "" ""
        return
    fi
    if [ ! -d "$path/.git" ] && [ ! -f "$path/.git" ]; then
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$path" "$role" "not_a_git_repo" "" "" "" ""
        return
    fi
    local head dirty
    head="$(git -C "$path" log -1 --format='%h %ci' 2>/dev/null || echo 'unknown')"
    if [ -n "$(git -C "$path" status --porcelain 2>/dev/null | head -1)" ]; then
        dirty="dirty"
    else
        dirty="clean"
    fi
    local archive_marker="absent"
    if [ -f "$path/ARCHIVE_POLICY.md" ]; then
        archive_marker="ARCHIVE_POLICY.md"
    fi
    # Lock marker probe: mirrors should carry a MIRROR_LOCK.md (human)
    # and MIRROR_LOCK.json (machine) plus an executable pre-commit hook
    # that refuses commits. Reported as a short summary string.
    local lock_state=""
    if [ "$role" = "mirror_archived" ]; then
        local have_md=0 have_json=0 have_hook=0
        [ -f "$path/MIRROR_LOCK.md" ] && have_md=1
        [ -f "$path/MIRROR_LOCK.json" ] && have_json=1
        local git_dir_rel
        git_dir_rel="$(git -C "$path" rev-parse --git-dir 2>/dev/null || echo ".git")"
        local git_dir
        case "$git_dir_rel" in
            /*) git_dir="$git_dir_rel" ;;
            *)  git_dir="$path/$git_dir_rel" ;;
        esac
        [ -x "$git_dir/hooks/pre-commit" ] && have_hook=1
        if [ "$have_md" -eq 1 ] && [ "$have_json" -eq 1 ] && [ "$have_hook" -eq 1 ]; then
            lock_state="locked"
        elif [ "$have_md" -eq 0 ] && [ "$have_json" -eq 0 ] && [ "$have_hook" -eq 0 ]; then
            lock_state="unlocked"
        else
            lock_state="partial(md=$have_md,json=$have_json,hook=$have_hook)"
        fi
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$path" "$role" "present" "$dirty" "$head" "$archive_marker" "$lock_state"
}

records=()
records+=("$(probe_repo "$CANONICAL_PATH" "canonical")")
for p in "${MIRROR_PATHS[@]}"; do
    records+=("$(probe_repo "$p" "mirror_archived")")
done

if [ "$OUTPUT_MODE" = "json" ]; then
    # Pass records via env (newline-joined TSV) so we don't conflict with
    # python3 reading its source from the heredoc.
    rec_blob=""
    for r in "${records[@]}"; do
        rec_blob+="$r"$'\n'
    done
    REC_BLOB="$rec_blob" CANONICAL_PATH="$CANONICAL_PATH" python3 - <<'PY'
import json, os
blob = os.environ.get("REC_BLOB", "")
out = []
for line in blob.split("\n"):
    if not line:
        continue
    parts = line.split("\t")
    while len(parts) < 7:
        parts.append("")
    out.append({
        "path": parts[0],
        "role": parts[1],
        "presence": parts[2],
        "git_state": parts[3],
        "head": parts[4],
        "archive_marker": parts[5],
        "lock_state": parts[6],
    })
print(json.dumps({"canonical_path": os.environ.get("CANONICAL_PATH", ""), "repos": out}, indent=2))
PY
else
    echo "Meridian workspace canonical/archive map"
    echo "  canonical: $CANONICAL_PATH"
    echo
    printf '  %-44s %-18s %-12s %-10s %-10s %s\n' "PATH" "ROLE" "PRESENCE" "GIT" "LOCK" "HEAD"
    for r in "${records[@]}"; do
        IFS=$'\t' read -r path role presence git_state head archive_marker lock_state <<< "$r"
        printf '  %-44s %-18s %-12s %-10s %-10s %s\n' "$path" "$role" "$presence" "${git_state:-}" "${lock_state:--}" "${head:-}"
    done
    echo
    echo "Notes:"
    echo "  - Only the canonical path receives new feature work."
    echo "  - Archived mirrors are kept for permalink stability."
    echo "  - See docs/REPO_MIGRATION_MAP.md for the GitHub-side map."
fi

if [ "$STRICT" -eq 1 ]; then
    failed=0
    for r in "${records[@]}"; do
        IFS=$'\t' read -r path role presence git_state head archive_marker lock_state <<< "$r"
        if [ "$role" = "mirror_archived" ] && [ "$presence" = "present" ]; then
            if [ "$git_state" = "dirty" ]; then
                # Tolerate dirtiness that is *only* the installed lock
                # markers. If any other file is modified, flag it.
                extra="$(git -C "$path" status --porcelain 2>/dev/null | \
                    awk '{print $2}' | \
                    grep -v -E '^(MIRROR_LOCK\.md|MIRROR_LOCK\.json)$' || true)"
                if [ -n "$extra" ]; then
                    echo "WARN: archived mirror has uncommitted divergence beyond lock markers: $path" >&2
                    failed=1
                fi
            fi
            if [ "$lock_state" != "locked" ]; then
                echo "WARN: archived mirror is not fully locked ($lock_state): $path" >&2
                echo "      reinstall with: bash scripts/install_mirror_locks.sh" >&2
                failed=1
            fi
        fi
    done
    [ "$failed" -eq 0 ] || exit 2
fi
