#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${OUTPUT_DIR:-${repo_root}/dist}"
kernel_path="${KERNEL_PATH:-/opt/meridian-kernel}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      output_dir="$2"
      shift 2
      ;;
    --kernel-path)
      kernel_path="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

artifact="$("$repo_root/scripts/package_release.sh" --kernel-path "$kernel_path" --output-dir "$output_dir")"
printf 'artifact=%s\n' "$artifact"
if [[ -f "${artifact}.sha256" ]]; then
  printf 'checksum=%s\n' "${artifact}.sha256"
fi
