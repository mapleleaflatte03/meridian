#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

KERNEL_PATH="${KERNEL_PATH:-/opt/meridian-kernel}"
OUTPUT_DIR="${OUTPUT_DIR:-$(mktemp -d /tmp/meridian-loom-release-verify.XXXXXX)}"
INSTALL_PREFIX="${INSTALL_PREFIX:-$(mktemp -d /tmp/meridian-loom-install-prefix.XXXXXX)}"
BIN_DIR="${BIN_DIR:-$(mktemp -d /tmp/meridian-loom-install-bin.XXXXXX)}"
RUNTIME_ROOT="${RUNTIME_ROOT:-$(mktemp -d /tmp/meridian-loom-runtime.XXXXXX)}"
SERVICE_TOKEN="${SERVICE_TOKEN:-loom-release-verify-token}"
IMAGE_NAME="${IMAGE_NAME:-meridian-loom:release-verify}"
CONTAINER_MODE="${CONTAINER_MODE:-auto}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --kernel-path)
      KERNEL_PATH="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --install-prefix)
      INSTALL_PREFIX="$2"
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="$2"
      shift 2
      ;;
    --root)
      RUNTIME_ROOT="$2"
      shift 2
      ;;
    --service-token)
      SERVICE_TOKEN="$2"
      shift 2
      ;;
    --image)
      IMAGE_NAME="$2"
      shift 2
      ;;
    --container)
      CONTAINER_MODE="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

mkdir -p "${OUTPUT_DIR}" "${INSTALL_PREFIX}" "${BIN_DIR}" "${RUNTIME_ROOT}"

ARTIFACT="$("${REPO_ROOT}/scripts/package_release.sh" --kernel-path "${KERNEL_PATH}" --output-dir "${OUTPUT_DIR}")"
"${REPO_ROOT}/scripts/install_local.sh" "${ARTIFACT}" --prefix "${INSTALL_PREFIX}" --bin-dir "${BIN_DIR}"

LOOM="${BIN_DIR}/loom" \
  "${REPO_ROOT}/scripts/acceptance_local_service.sh" \
  --root "${RUNTIME_ROOT}" \
  --kernel-path "${KERNEL_PATH}" \
  --service-token "${SERVICE_TOKEN}"

CONTAINER_STATUS="skipped"
if [[ "${CONTAINER_MODE}" != "never" ]] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  "${REPO_ROOT}/scripts/acceptance_container_service.sh" \
    --image "${IMAGE_NAME}" \
    --kernel-path "${KERNEL_PATH}" \
    --service-token "${SERVICE_TOKEN}" \
    --build-image always
  CONTAINER_STATUS="passed"
elif [[ "${CONTAINER_MODE}" == "always" ]]; then
  echo "container verification requested but Docker is unavailable" >&2
  exit 1
fi

echo "artifact=${ARTIFACT}"
echo "install_prefix=${INSTALL_PREFIX}"
echo "bin_dir=${BIN_DIR}"
echo "runtime_root=${RUNTIME_ROOT}"
echo "container_status=${CONTAINER_STATUS}"
