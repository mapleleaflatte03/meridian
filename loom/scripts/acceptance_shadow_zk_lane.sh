#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

run_shadow_zk_test() {
  local test_name="$1"
  shift
  "${SCRIPT_DIR}/acceptance_shadow_zk.sh" --test-name "${test_name}" "$@"
}

echo "[loom-acceptance-lane] stage=shadow_zk_core"
run_shadow_zk_test "acceptance_shadow_zk_one_command_lane" "$@"

echo "[loom-acceptance-lane] stage=shadow_zk_embodied_core"
run_shadow_zk_test "acceptance_shadow_ros2_physical_zk_lane" "$@"

echo "[loom-acceptance-lane] stage=shadow_wasmtime_requires_warrant"
run_shadow_zk_test "shadow_run_wasmtime_requires_warrant_file" "$@"

echo "[loom-acceptance-lane] stage=shadow_wasmtime_typed_capture"
run_shadow_zk_test "shadow_run_wasmtime_writes_verified_warrant_and_report_artifacts" "$@"

echo "[loom-acceptance-lane] stage=shadow_alias_agent_ref_canonicalization"
run_shadow_zk_test "job_settle_zk_canonicalizes_alias_agent_ref_before_treasury" "$@"

echo "[loom-acceptance-lane] stage=typed_shadow_report"
(cd "${REPO_ROOT}" && cargo test -p loom-shadow shadow_report_prefers_typed_shadow_and_settlement_views -- --nocapture)

echo "[loom-acceptance-lane] stage=typed_parity_report"
(cd "${REPO_ROOT}" && cargo test -p loom-shadow parity_report_prefers_typed_reference_and_comparison_artifacts -- --nocapture)

echo "[loom-acceptance-lane] stage=shadow_backend_registry"
(cd "${REPO_ROOT}" && cargo test -p loom-shadow shadow_backend_plugin_registry_covers_all_backends -- --nocapture)

echo "[loom-acceptance-lane] stage=grpc_action_typed_capture"
run_shadow_zk_test "shadow_run_grpc_action_backend_writes_typed_report_artifacts" "$@"

echo "[loom-acceptance-lane] stage=grpc_physical_typed_capture"
run_shadow_zk_test "shadow_run_grpc_physical_backend_writes_embodied_typed_artifacts" "$@"

echo "[loom-acceptance-lane] stage=grpc_physical_stream_ack_lifecycle"
run_shadow_zk_test "shadow_run_grpc_physical_stream_ack_lifecycle_records_ack" "$@"

echo "[loom-acceptance-lane] stage=grpc_physical_stream_ack_timeout_cancel"
run_shadow_zk_test "shadow_run_grpc_physical_stream_ack_timeout_cancels" "$@"

echo "[loom-acceptance-lane] stage=ros2_physical_typed_capture"
run_shadow_zk_test "shadow_run_ros2_physical_backend_writes_embodied_typed_artifacts" "$@"

echo "[loom-acceptance-lane] stage=ros2_physical_action_typed_capture"
run_shadow_zk_test "shadow_run_ros2_physical_action_mode_writes_embodied_typed_artifacts" "$@"

echo "[loom-acceptance-lane] stage=ros2_physical_action_cancel_typed_capture"
run_shadow_zk_test "shadow_run_ros2_physical_action_cancel_after_writes_aborted_diagnostics" "$@"

echo "[loom-acceptance-lane] PASS"
