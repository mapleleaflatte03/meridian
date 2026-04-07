#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/../fixture_kernel_local.sh"

LOOM="${LOOM:-${REPO_ROOT}/target/debug/loom}"
ROOT_DIR="${1:-/tmp/loom-phase2-portability-corpus}"
FIXTURE_KERNEL="${2:-/tmp/loom-phase2-portability-kernel}"
MANIFEST="${CORPUS_MANIFEST:-${REPO_ROOT}/examples/phase2-portability-corpus-manifest.json}"

cleanup() {
  rm -rf "${ROOT_DIR}" "${FIXTURE_KERNEL}"
}
trap cleanup EXIT

ensure_debug_loom_binary() {
  local repo_root="$1"
  if [[ ! -x "${LOOM}" ]]; then
    echo "Binary not found at ${LOOM}, building..."
    (cd "${repo_root}" && cargo build --workspace)
  fi
}

read_manifest_rows() {
  python3 - <<'PY' "$1"
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
sources = manifest.get("sources", [])
if len(sources) < 2:
    raise SystemExit("phase 2 portability corpus needs at least two sources")
for source in sources:
    print("|".join([
        source["skill_name"],
        source["source_root"],
        source["expected_capability_name"],
    ]))
PY
}

verify_registry_contains_corpus() {
  python3 - <<'PY' "$1" "$2" "$3"
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
loom = sys.argv[2]
manifest = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
resolved = []
for source in manifest.get("sources", []):
    name = source["expected_capability_name"]
    source_root = source["source_root"]
    raw = subprocess.check_output(
        [loom, "capability", "show", "--root", str(root), "--name", name, "--format", "json"],
        text=True,
    )
    capability = json.loads(raw)
    if capability.get("source_path") != source_root:
        raise SystemExit(f"unexpected source root for {name}: {capability.get('source_path')}")
    resolved.append(name)
print(json.dumps({
    "corpus_name": manifest.get("corpus_name", "phase2_portability_corpus_v0"),
    "imported_capabilities": sorted(resolved),
    "registry_size": len(resolved),
}, indent=2))
PY
}

echo "== Meridian Loom // Phase 2 Portability Corpus Slice =="
echo "root:        ${ROOT_DIR}"
echo "kernel:      ${FIXTURE_KERNEL}"
echo "manifest:    ${MANIFEST}"
echo ""

ensure_debug_loom_binary "${REPO_ROOT}"
write_local_fixture_kernel "${FIXTURE_KERNEL}" "phase 2 portability corpus slice"
rm -rf "${ROOT_DIR}"
mkdir -p "${ROOT_DIR}"

echo "--- Step 1: Initialize embedded workspace ---"
"${LOOM}" init \
  --mode embedded \
  --root "${ROOT_DIR}" \
  --kernel-path "${FIXTURE_KERNEL}" \
  --org-id org_tutorial
echo ""

echo "--- Step 2: Import real backup-snapshot skill roots ---"
while IFS='|' read -r skill_name source_root capability_name; do
  echo ">>> ${skill_name}"
  [[ -f "${source_root}/SKILL.md" ]] || {
    echo "missing skill doc: ${source_root}/SKILL.md" >&2
    exit 1
  }
  script_count="$(find "${source_root}/scripts" -maxdepth 1 -type f -name '*.py' | wc -l | tr -d ' ')"
  if [[ "${script_count}" != "1" ]]; then
    echo "unsupported script count for ${source_root}: ${script_count}" >&2
    exit 1
  fi
  "${LOOM}" capability import-workspace-skill \
    --root "${ROOT_DIR}" \
    --skill-root "${source_root}"
  echo ""
done < <(read_manifest_rows "${MANIFEST}")

echo "--- Step 3: Verify the corpus is usable ---"
verify_registry_contains_corpus "${ROOT_DIR}" "${LOOM}" "${MANIFEST}"
echo ""
echo "== Phase 2 portability corpus slice complete =="
