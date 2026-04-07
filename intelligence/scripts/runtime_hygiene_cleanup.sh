#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
PRUNE_TMP=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi
if [[ "${1:-}" == "--prune-tmp" || "${2:-}" == "--prune-tmp" ]]; then
  PRUNE_TMP=1
fi
MAX_TMP_DELETE="${MERIDIAN_RUNTIME_CLEANUP_MAX_TMP_DELETE:-300}"

count_proc() {
  local pattern="$1"
  pgrep -af "$pattern" | wc -l || true
}

count_tmp_dirs() {
  local name_glob="$1"
  find /tmp -maxdepth 1 -type d -name "$name_glob" 2>/dev/null | wc -l || true
}

kill_pattern() {
  local pattern="$1"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] pkill -f \"$pattern\""
    return
  fi
  pkill -f "$pattern" >/dev/null 2>&1 || true
}

clean_tmp_dirs() {
  local name_glob="$1"
  local candidates=()
  mapfile -t candidates < <(find /tmp -maxdepth 1 -type d -name "$name_glob" -mmin +30 2>/dev/null | head -n "${MAX_TMP_DELETE}")
  local candidate_count="${#candidates[@]}"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] prune_glob=${name_glob} candidates=${candidate_count} max=${MAX_TMP_DELETE}"
    return
  fi
  if [[ "${candidate_count}" -eq 0 ]]; then
    return
  fi
  printf '%s\0' "${candidates[@]}" | xargs -0 rm -rf -- 2>/dev/null || true
}

before_loom_loops="$(count_proc '/home/ubuntu/meridian-loom/target/debug/loom service loop')"
before_playwright_chrome="$(count_proc 'playwright_chromiumdev_profile')"
before_loom_tmp="$(count_tmp_dirs 'loom_*')"
before_playwright_tmp="$(count_tmp_dirs 'playwright_chromiumdev_profile-*')"

echo "=== runtime_hygiene_cleanup: before ==="
echo "loom_debug_service_loops=${before_loom_loops}"
echo "playwright_headless_chrome=${before_playwright_chrome}"
echo "tmp_loom_dirs=${before_loom_tmp}"
echo "tmp_playwright_profiles=${before_playwright_tmp}"

kill_pattern '/home/ubuntu/meridian-loom/target/debug/loom service loop'
kill_pattern 'playwright_chromiumdev_profile'

if [[ "$PRUNE_TMP" -eq 1 ]]; then
  clean_tmp_dirs 'loom_*'
  clean_tmp_dirs 'playwright_chromiumdev_profile-*'
else
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] skip_tmp_prune=true (pass --prune-tmp to enable)"
  else
    echo "[info] skip_tmp_prune=true (pass --prune-tmp to enable)"
  fi
fi

sleep 1

after_loom_loops="$(count_proc '/home/ubuntu/meridian-loom/target/debug/loom service loop')"
after_playwright_chrome="$(count_proc 'playwright_chromiumdev_profile')"
after_loom_tmp="$(count_tmp_dirs 'loom_*')"
after_playwright_tmp="$(count_tmp_dirs 'playwright_chromiumdev_profile-*')"

echo "=== runtime_hygiene_cleanup: after ==="
echo "loom_debug_service_loops=${after_loom_loops}"
echo "playwright_headless_chrome=${after_playwright_chrome}"
echo "tmp_loom_dirs=${after_loom_tmp}"
echo "tmp_playwright_profiles=${after_playwright_tmp}"
