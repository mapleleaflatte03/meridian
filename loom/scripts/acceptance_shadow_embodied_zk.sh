#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"${SCRIPT_DIR}/acceptance_shadow_zk.sh" --test-name acceptance_shadow_ros2_physical_zk_lane "$@"
