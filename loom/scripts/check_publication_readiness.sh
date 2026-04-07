#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

required_files=(
  "Cargo.toml"
  "README.md"
  "LICENSE"
  "loom.toml.example"
  ".github/workflows/rust.yml"
  "docs/assets/meridian_loom_lockup.svg"
  "docs/assets/loom_runtime_panels.svg"
  "docs/SETUP_REHEARSAL.md"
  "docs/PUBLICATION_CHECKLIST.md"
)

echo "== Meridian Loom publication readiness =="
echo "repo: $ROOT"

for path in "${required_files[@]}"; do
  if [[ -f "$path" ]]; then
    echo "[OK]   $path"
  else
    echo "[FAIL] missing $path"
    exit 1
  fi
done

echo
echo "== cargo test =="
cargo test --workspace

echo
echo "== cargo build =="
cargo build --workspace

echo
echo "== setup rehearsal =="
REHEARSAL_ROOT="$(mktemp -d /tmp/meridian-loom-publication.XXXXXX)"
./scripts/tests/rehearse_setup.sh "$REHEARSAL_ROOT" >/tmp/meridian-loom-publication-rehearsal.txt
echo "[OK]   rehearsal transcript refreshed at /tmp/meridian-loom-publication-rehearsal.txt"

echo
echo "== git status =="
git status --short

echo
echo "== remote origin =="
if git remote get-url origin >/tmp/meridian-loom-origin.txt 2>&1; then
  cat /tmp/meridian-loom-origin.txt
else
  cat /tmp/meridian-loom-origin.txt
  echo
  echo "[WARN] origin is not configured."
fi

echo
echo "== GitHub API visibility =="
if gh api repos/mapleleaflatte03/meridian-loom --jq '.html_url' >/tmp/meridian-loom-public-url.txt 2>&1; then
  cat /tmp/meridian-loom-public-url.txt
else
  cat /tmp/meridian-loom-public-url.txt
  echo
  echo "[WARN] GitHub API could not confirm public repository visibility."
fi
