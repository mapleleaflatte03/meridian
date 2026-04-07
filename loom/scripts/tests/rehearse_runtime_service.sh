#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ROOT_DIR="${1:-/tmp/loom-runtime-service}"
SOURCE_KERNEL="${SOURCE_KERNEL:-/tmp/meridian-kernel}"
SERVICE_TOKEN="${SERVICE_TOKEN:-loom-local-token}"

echo "== Meridian Loom runtime service rehearsal =="
echo "root:   ${ROOT_DIR}"
echo "kernel: ${SOURCE_KERNEL}"
echo "mode:   local service lifecycle + HTTP control plane"

"${SCRIPT_DIR}/../acceptance_local_service.sh" \
  --root "${ROOT_DIR}" \
  --kernel-path "${SOURCE_KERNEL}" \
  --service-token "${SERVICE_TOKEN}" \
  --org-id org_demo

echo "== Runtime service rehearsal complete =="
