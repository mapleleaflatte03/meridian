#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SKIP_TESTS="false"
SKIP_ACCEPTANCE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-tests)
      SKIP_TESTS="true"
      shift
      ;;
    --skip-acceptance)
      SKIP_ACCEPTANCE="true"
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

echo "[dev-first-proof] repo=${REPO_ROOT}"

if [[ "${SKIP_TESTS}" != "true" ]]; then
  echo "[dev-first-proof] running quickstart integration test"
  (cd "${REPO_ROOT}" && cargo test -p meridian-loom --test quickstart -- --nocapture)
fi

if [[ "${SKIP_ACCEPTANCE}" != "true" ]]; then
  echo "[dev-first-proof] running quickstart acceptance lane"
  (cd "${REPO_ROOT}" && ./scripts/acceptance_quickstart_lane.sh)
fi

cat <<'EOF'
[dev-first-proof] PASS
Next:
  1. make acceptance-security-auth-lane
  2. make acceptance-observability-lane
  3. loom observe summary --root "$HOME/.local/share/meridian-loom/runtime/default" --fix-hints --format human
EOF
