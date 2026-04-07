#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SCRIPT_DIR}/../fixture_kernel_local.sh"

LOOM="${LOOM:-${REPO_ROOT}/target/debug/loom}"
ROOT_DIR="${1:-/tmp/loom-legacy-plugin-import}"
FIXTURE_KERNEL="$(mktemp -d /tmp/loom-legacy-plugin-kernel.XXXXXX)"
PLUGIN_ROOT="$(mktemp -d /tmp/loom-legacy-plugin-fixture.XXXXXX)"
PLUGIN_SKILL_ROOT="${PLUGIN_ROOT}/skills/alpha-scan"
CAPABILITY_NAME="clawskill.acme-plugin.alpha-scan.v0"
ORG_ID="${ORG_ID:-org_tutorial}"

cleanup() {
  rm -rf "${FIXTURE_KERNEL}" "${PLUGIN_ROOT}" "${ROOT_DIR}"
}
trap cleanup EXIT

echo "== Meridian Loom // Legacy Plugin Import Rehearsal =="
echo "root:   ${ROOT_DIR}"
echo "kernel: ${FIXTURE_KERNEL}"
echo "plugin: ${PLUGIN_ROOT}"
echo ""

ensure_debug_loom_binary "${REPO_ROOT}"
write_local_fixture_kernel "${FIXTURE_KERNEL}" "legacy plugin import rehearsal"

rm -rf "${ROOT_DIR}"
mkdir -p "${PLUGIN_SKILL_ROOT}"

cat > "${PLUGIN_ROOT}/legacy.plugin.json" <<'JSON'
{
  "id": "acme-plugin",
  "configSchema": {
    "type": "object",
    "title": "Legacy plugin config"
  },
  "skills": "skills"
}
JSON

cat > "${PLUGIN_SKILL_ROOT}/SKILL.md" <<'EOF_SKILL'
---
name: alpha-scan
description: Alpha scan skill
---

# Alpha Scan
EOF_SKILL

cat > "${PLUGIN_ROOT}/package.json" <<'JSON'
{ "name": "acme-plugin" }
JSON

echo "--- Step 1: Initialize workspace ---"
"${LOOM}" init \
  --mode embedded \
  --kernel-path "${FIXTURE_KERNEL}" \
  --root "${ROOT_DIR}" \
  --org-id "${ORG_ID}"
echo ""

echo "--- Step 2: Import legacy plugin subset ---"
"${LOOM}" capability import-legacy-plugin-skill-subset \
  --root "${ROOT_DIR}" \
  --plugin-root "${PLUGIN_ROOT}"
echo ""

echo "--- Step 3: Show imported capability ---"
"${LOOM}" capability show \
  --root "${ROOT_DIR}" \
  --name "${CAPABILITY_NAME}"
