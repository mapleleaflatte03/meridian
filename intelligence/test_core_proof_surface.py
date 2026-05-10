#!/usr/bin/env python3
"""Tests for Meridian Core proof surface."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"
VERIFY_SH = MERIDIAN_ROOT / "scripts" / "verify_core_runtime_local.sh"


class TestProofHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_proof_local(self):
        self.assertIn("proof local", self.help_text)

    def test_help_mentions_proof_show(self):
        self.assertIn("proof show", self.help_text)

    def test_help_mentions_proof_path(self):
        self.assertIn("proof path", self.help_text)

    def test_help_mentions_proof_summary(self):
        self.assertIn("proof summary", self.help_text)


class TestProofSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_main_dispatch_includes_proof(self):
        self.assertIn('proof)       cmd_proof "$@" ;;', self.source)

    def test_proof_local_wraps_verify_script(self):
        self.assertIn("verify_core_runtime_local.sh", self.source)
        self.assertIn("CORE_LAST_PROOF_FILE", self.source)
        self.assertIn('die "Usage: core.sh proof <local|show|summary|path>"', self.source)
        self.assertIn('summary)', self.source)


class TestProofScriptCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = VERIFY_SH.read_text(encoding="utf-8")

    def test_proof_covers_provider_mutation(self):
        self.assertIn("provider mutation in isolated kernel root", self.source)
        self.assertIn("provider_mutation_ok", self.source)
        self.assertIn("MERIDIAN_KERNEL_ROOT=/tmp/core-proof-kernel", self.source)

    def test_proof_covers_provider_restore(self):
        self.assertIn("checking provider restore in isolated env root", self.source)
        self.assertIn("provider_restore_ok", self.source)
        self.assertIn("MERIDIAN_LOCAL_ENV_DIR=/tmp/core-proof-local-env", self.source)
        self.assertIn("./scripts/core.sh provider fix", self.source)
        self.assertIn("provider_restore_probe", self.source)
        self.assertIn('"[core] provider fix" in sections["provider_restore"]', self.source)
        self.assertIn("route_id:     route_primary", self.source)

    def test_proof_covers_config_mutation(self):
        self.assertIn("config mutation in isolated loom root", self.source)
        self.assertIn("config_mutation_ok", self.source)
        self.assertIn("MERIDIAN_LOOM_ROOT=/tmp/core-proof-loom", self.source)

    def test_proof_covers_doctor_surface(self):
        self.assertIn("checking doctor surface", self.source)
        self.assertIn("doctor_surface_ok", self.source)
        self.assertIn("./scripts/core.sh doctor fix", self.source)
        self.assertIn("./scripts/core.sh doctor summary", self.source)
        self.assertIn('"[core] doctor fix:" in sections["doctor"]', self.source)
        self.assertIn('and "CRITICAL=0" in sections["doctor_summary"]', self.source)

    def test_proof_reports_ingress_counts(self):
        self.assertIn('"ingress_pending_count"', self.source)
        self.assertIn('"ingress_quarantine_count"', self.source)

    def test_proof_covers_channel_diagnostics_and_proof(self):
        self.assertIn("[verify-core] checking multi-channel diagnostics (file-based)", self.source)
        self.assertIn("./scripts/core.sh channel diagnostics", self.source)
        self.assertIn("./scripts/core.sh channel diagnostics telegram 5", self.source)
        self.assertIn("./scripts/core.sh channel diagnostics zalo 5", self.source)
        self.assertIn("./scripts/core.sh channel proof telegram 5", self.source)
        self.assertIn("./scripts/core.sh channel proof web_api 5", self.source)
        self.assertIn('"channel_diagnostics_surface_ok"', self.source)
        self.assertIn('"channel_proof_surface_ok"', self.source)
        self.assertIn('"channel_health_channel_count"', self.source)
        self.assertIn('"telegram_proof_receipt_count"', self.source)
        self.assertIn('"webapi_proof_receipt_count"', self.source)

    def test_proof_covers_memory_governance_surface(self):
        self.assertIn("[verify-core] checking governed memory fork/replay", self.source)
        self.assertIn("[verify-core] checking governed memory status snapshot", self.source)
        self.assertIn("[verify-core] checking governed memory workflow showcase", self.source)
        self.assertIn("[verify-core] checking governed memory team topology", self.source)
        self.assertIn("[verify-core] checking governed memory team summary", self.source)
        self.assertIn('curl -sS http://127.0.0.1:8266/api/status', self.source)
        self.assertIn('curl -sS http://127.0.0.1:8266/api/runtime-proof', self.source)
        self.assertIn('curl -sS http://127.0.0.1:8266/api/workflows/showcase', self.source)
        self.assertIn('curl -sS http://127.0.0.1:8266/api/team/topology', self.source)
        self.assertIn('curl -sS http://127.0.0.1:8266/api/team/governed-memory', self.source)
        self.assertIn("./scripts/core.sh memory fork agent_atlas --target-agent agent_quill", self.source)
        self.assertIn("./scripts/core.sh memory replay agent_atlas --target-agent agent_quill", self.source)
        self.assertIn("./scripts/core.sh memory latest-fork --json", self.source)
        self.assertIn("./scripts/core.sh memory latest-replay --json", self.source)
        self.assertIn("./scripts/core.sh memory fork-history 5 --json", self.source)
        self.assertIn("./scripts/core.sh memory replay-history 5 --json", self.source)
        self.assertIn("./scripts/core.sh memory governance 5 --json", self.source)
        self.assertIn('"memory_governance_surface_ok"', self.source)
        self.assertIn('"memory_latest_fork_surface_ok"', self.source)
        self.assertIn('"memory_latest_replay_surface_ok"', self.source)
        self.assertIn('"memory_history_surface_ok"', self.source)
        self.assertIn('"memory_governance_summary_surface_ok"', self.source)
        self.assertIn('"governed_memory_status_surface_ok"', self.source)
        self.assertIn('"memory_taxonomy_status_surface_ok"', self.source)
        self.assertIn('"provider_runtime_status_surface_ok"', self.source)
        self.assertIn('"provider_runtime_runtime_proof_surface_ok"', self.source)
        self.assertIn('"governed_memory_showcase_surface_ok"', self.source)
        self.assertIn('"memory_taxonomy_showcase_surface_ok"', self.source)
        self.assertIn('"provider_runtime_showcase_surface_ok"', self.source)
        self.assertIn('"governed_memory_team_topology_ok"', self.source)
        self.assertIn('"governed_memory_team_summary_ok"', self.source)
        self.assertIn('"provider_surface_truth_ok"', self.source)
        self.assertIn('"recent_actions"', self.source)
        self.assertIn('"memory_fork_selected_entries"', self.source)
        self.assertIn('"memory_replay_replayed_entries"', self.source)
        self.assertIn('"memory_fork_history_count"', self.source)
        self.assertIn('"memory_replay_history_count"', self.source)
        self.assertIn('"memory_governance_fork_recent_count"', self.source)
        self.assertIn('"memory_governance_replay_recent_count"', self.source)
        self.assertIn('"governed_memory_status_replay_latest"', self.source)
        self.assertIn('"memory_taxonomy_status_tag_count"', self.source)
        self.assertIn('"provider_runtime_source"', self.source)
        self.assertIn('"provider_runtime_runtime_proof_source"', self.source)
        self.assertIn('"provider_runtime_override_active"', self.source)
        self.assertIn('"provider_runtime_drift_count"', self.source)
        self.assertIn('"provider_runtime_runtime_proof_drift_count"', self.source)
        self.assertIn('"provider_runtime_showcase_drift_value"', self.source)
        self.assertIn('"governed_memory_showcase_operator_value"', self.source)
        self.assertIn('"memory_taxonomy_showcase_tag_count"', self.source)
        self.assertIn('"governed_memory_team_specialist_count"', self.source)
        self.assertIn('"memory_taxonomy_team_tag_count"', self.source)
        self.assertIn('"provider_runtime_team_drift_count"', self.source)
        self.assertIn('"governed_memory_team_agent_count"', self.source)
        self.assertIn('"governed_memory_team_active_agent_count"', self.source)
        self.assertIn('"governed_memory_team_replay_latest"', self.source)
        self.assertIn('"memory_replay_target_entry_count"', self.source)
        self.assertIn("[verify-core] checking agent inspect operator view", self.source)
        self.assertIn("./scripts/core.sh agent inspect", self.source)
        self.assertIn('"agent_inspect_governed_memory_ok"', self.source)

    def test_proof_covers_files_surface(self):
        self.assertIn("[verify-core] checking persistent file queue", self.source)
        self.assertIn('"files_surface_ok"', self.source)
        self.assertIn('"queued_files_count"', self.source)

    def test_proof_covers_response_meta_provider_runtime(self):
        self.assertIn('PROOF_ASK_SESSION="proof-ask-$$"', self.source)
        self.assertIn('PROOF_ASK_GATEWAY_URL=', self.source)
        self.assertIn('start_proof_ask_runtime', self.source)
        self.assertIn('MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" ./scripts/core.sh ask --session "$PROOF_ASK_SESSION" "Reply with exactly: core-proof-ok"', self.source)
        self.assertIn('./scripts/core.sh response meta >/tmp/verify-core-response-meta.txt', self.source)
        self.assertIn('"response_meta_provider_runtime_ok"', self.source)
        self.assertIn('"response_meta_provider_source"', self.source)
        self.assertIn('"response_meta_provider_profile"', self.source)
        self.assertIn('"response_meta_provider_transport"', self.source)

    def test_proof_captures_live_provider_probe_distinct_from_isolated_ask_lane(self):
        self.assertIn("[verify-core] checking live provider probe (best effort)", self.source)
        self.assertIn("./scripts/core.sh provider probe >/tmp/verify-core-provider-live-probe.txt 2>&1", self.source)
        self.assertIn('"provider_live_probe_ok"', self.source)
        self.assertIn('"provider_live_probe_error_code"', self.source)
        self.assertIn('"lane_truth"', self.source)
        self.assertIn('"live_provider_probe"', self.source)
        self.assertIn('"isolated_ask_lane"', self.source)
        self.assertIn('"split_truth_explicit"', self.source)

    def test_proof_covers_context_surface(self):
        self.assertIn("[verify-core] checking persistent context files", self.source)
        self.assertIn("[verify-core] starting isolated proof ask runtime", self.source)
        self.assertIn('"context_surface_ok"', self.source)
        self.assertIn('"context_files_count"', self.source)
        self.assertIn('MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" ./scripts/core.sh ask --session "$PROOF_CONTEXT_NOCTX_SESSION" --no-context "Reply with exactly: no-context-proof-ok"', self.source)

    def test_proof_covers_playbook_surface(self):
        self.assertIn("[verify-core] checking playbook surface", self.source)
        self.assertIn('"playbook_surface_ok"', self.source)
        self.assertIn('"playbook_count"', self.source)
        self.assertIn('PROOF_PLAYBOOK_SESSION="proof-playbook-$$"', self.source)
        self.assertIn('MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" MERIDIAN_SESSION_ID="$PROOF_PLAYBOOK_SESSION" ./scripts/core.sh playbook run release-qa', self.source)
        self.assertIn("./scripts/core.sh playbook capture captured-proof", self.source)
        self.assertIn("./scripts/core.sh playbook every release-qa 3600", self.source)
        self.assertIn("./scripts/core.sh playbook schedules", self.source)
        self.assertIn('PROOF_PLAYBOOK_SCHEDULED_SESSION="proof-playbook-scheduled-$$"', self.source)
        self.assertIn('MERIDIAN_GATEWAY_URL="${PROOF_ASK_GATEWAY_URL}" MERIDIAN_SESSION_ID="$PROOF_PLAYBOOK_SCHEDULED_SESSION" ./scripts/core.sh playbook run-scheduled playbook-release-qa', self.source)
        self.assertIn("./scripts/core.sh playbook unschedule release-qa", self.source)
        self.assertIn('"playbook_schedule_count"', self.source)

    def test_proof_covers_session_resume_bridge(self):
        self.assertIn("[verify-core] checking session resume bridge", self.source)
        self.assertIn('"session_resume_ok"', self.source)
        self.assertIn('"session_resume_queue_count"', self.source)
        self.assertIn('"session_resume_context_count"', self.source)
        self.assertIn("session resume web_api:exportproof 281 --queue", self.source)
        self.assertIn("session resume web_api:exportproof 281 --context", self.source)

    def test_proof_covers_session_reuse_bridge(self):
        self.assertIn("[verify-core] checking session reuse bridge", self.source)
        self.assertIn('"session_reuse_ok"', self.source)
        self.assertIn('"session_reuse_queue_count"', self.source)
        self.assertIn('"session_reuse_context_count"', self.source)
        self.assertIn('session reuse "core-proof-ok" --queue', self.source)
        self.assertIn('session reuse "core-proof-ok" --context', self.source)

    def test_proof_status_is_not_hardcoded_pass(self):
        self.assertIn('failed_checks = sorted(key for key, value in summary.items() if not value)', self.source)
        self.assertIn('status = "pass" if not failed_checks else "fail"', self.source)
        self.assertIn('[verify-core] RESULT: FAIL', self.source)


if __name__ == "__main__":
    unittest.main()
