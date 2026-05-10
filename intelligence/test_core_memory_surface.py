#!/usr/bin/env python3
"""Tests for Meridian Core memory recall and governed memory surface.

Covers:
- core.sh memory search subcommand wiring and dispatch
- core.sh recall accepts --text and --limit flags
- Help text exposes search and recall options
- Cross-agent fan-out flag is wired and renders [agent/category] rows
- Governed memory fork/replay wrappers are surfaced in Core
"""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestMemorySurfaceHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_memory_search(self):
        self.assertIn("memory search QUERY", self.help_text)

    def test_help_mentions_all_agents_flag(self):
        self.assertIn("--all-agents", self.help_text)

    def test_help_mentions_recall_text_and_limit(self):
        self.assertIn("recall [KEY_PREFIX] [--text Q] [--limit N]", self.help_text)


class TestMemorySurfaceSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_memory_search_subcommand_dispatch(self):
        # cmd_memory dispatches "search" to cmd_memory_search.
        self.assertIn("search)\n            cmd_memory_search", self.source)

    def test_memory_search_function_exists(self):
        self.assertIn("cmd_memory_search()", self.source)

    def test_memory_search_passes_text_flag_to_loom(self):
        # Build the loom args correctly with --text.
        self.assertIn('"--text" "$query"', self.source)

    def test_memory_search_supports_all_agents(self):
        self.assertIn("--all-agents", self.source)
        self.assertIn('args+=("--all-agents")', self.source)

    def test_memory_search_clamps_to_resolved_agent_id_when_not_all_agents(self):
        # When all_agents flag is unset, agent_id must be resolved and passed.
        self.assertIn('args+=("--agent-id" "$agent_id")', self.source)

    def test_memory_search_renders_agent_id_when_fanned_out(self):
        # Output rows include [agent/category] prefix only when SHOW_AGENT=1.
        self.assertIn("[{agent}/{cat}]", self.source)

    def test_recall_supports_text_flag(self):
        # cmd_recall must parse --text and forward it to loom memory search.
        self.assertIn("text_query=", self.source)
        self.assertIn('args+=("--text" "$text_query")', self.source)

    def test_recall_supports_limit_flag(self):
        self.assertIn('args+=("--limit" "$limit")', self.source)

    def test_recall_preserves_key_prefix_default(self):
        # Default behavior (no flags) must still pass --key-prefix.
        self.assertIn('args+=("--key-prefix" "$prefix")', self.source)

    def test_memory_search_usage_string_lists_all_agents(self):
        self.assertIn(
            "Usage: core.sh memory search QUERY [LIMIT] [--all-agents]",
            self.source,
        )


def _help_block(source: str) -> str:
    """Return the cmd_help() heredoc block so individual help lines can be
    asserted without false positives matching the rest of the script.

    The same banner appears twice (file header comment and the heredoc
    body), so we skip the first hit and slice from the second one.
    """
    marker = "Meridian Core — daily-use task runner"
    first = source.find(marker)
    if first < 0:
        return source
    second = source.find(marker, first + len(marker))
    start = second if second >= 0 else first
    return source[start : start + 8000]


class TestMemorySnapshotSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_lists_memory_snapshot(self):
        self.assertIn("memory snapshot DIR", _help_block(self.source))

    def test_memory_snapshot_dispatched_from_cmd_memory(self):
        self.assertIn("snapshot)\n            cmd_memory_snapshot", self.source)

    def test_memory_snapshot_function_exists(self):
        self.assertIn("cmd_memory_snapshot()", self.source)

    def test_memory_snapshot_supports_all_agents_flag(self):
        # Function must parse --all-agents and switch scope.
        self.assertIn('scope="all_agents"', self.source)
        self.assertIn('memory_root="$LOOM_ROOT/state/memory"', self.source)

    def test_memory_snapshot_writes_manifest(self):
        # Manifest path is named exactly _manifest.json so operators can
        # reliably enumerate snapshots.
        self.assertIn("_manifest.json", self.source)
        self.assertIn('"version": 1', self.source)
        self.assertIn('"snapshot_at_unix"', self.source)
        self.assertIn('"total_entry_count"', self.source)


class TestMemoryForkReplaySurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_lists_memory_fork(self):
        self.assertIn("memory fork SOURCE_REF", _help_block(self.source))

    def test_help_lists_memory_replay(self):
        self.assertIn("memory replay SOURCE_REF", _help_block(self.source))

    def test_help_lists_memory_latest_artifacts(self):
        self.assertIn("memory latest-fork [--json]", _help_block(self.source))
        self.assertIn("memory latest-replay [--json]", _help_block(self.source))
        self.assertIn("memory fork-history [N] [--json]", _help_block(self.source))
        self.assertIn("memory replay-history [N] [--json]", _help_block(self.source))
        self.assertIn("memory governance [N] [--json]", _help_block(self.source))
        self.assertIn("memory team-governance [N] [--json]", _help_block(self.source))

    def test_memory_fork_dispatched_from_cmd_memory(self):
        self.assertIn("fork)\n            cmd_memory_fork", self.source)

    def test_memory_replay_dispatched_from_cmd_memory(self):
        self.assertIn("replay)\n            cmd_memory_replay", self.source)

    def test_memory_latest_artifacts_dispatched_from_cmd_memory(self):
        self.assertIn("latest-fork)\n            cmd_memory_latest_artifact fork", self.source)
        self.assertIn("latest-replay)\n            cmd_memory_latest_artifact replay", self.source)
        self.assertIn("fork-history)\n            cmd_memory_artifact_history fork", self.source)
        self.assertIn("replay-history)\n            cmd_memory_artifact_history replay", self.source)
        self.assertIn("governance)\n            cmd_memory_governance_summary", self.source)
        self.assertIn("team-governance)\n            cmd_memory_team_governance", self.source)

    def test_memory_fork_function_exists(self):
        self.assertIn("cmd_memory_fork()", self.source)

    def test_memory_replay_function_exists(self):
        self.assertIn("cmd_memory_replay()", self.source)

    def test_memory_latest_artifact_function_exists(self):
        self.assertIn("cmd_memory_latest_artifact()", self.source)
        self.assertIn("cmd_memory_artifact_history()", self.source)
        self.assertIn("cmd_memory_governance_summary()", self.source)
        self.assertIn("cmd_memory_team_governance()", self.source)

    def test_memory_fork_requires_target_agent(self):
        self.assertIn('die "--target-agent is required"', self.source)
        self.assertIn('"fork" "$source_ref" "--target-agent-id" "$target_agent"', self.source)

    def test_memory_replay_requires_target_agent(self):
        self.assertIn('die "--target-agent is required"', self.source)
        self.assertIn('"replay" "$source_ref" "--target-agent-id" "$target_agent"', self.source)

    def test_memory_replay_passes_kernel_and_org_boundary(self):
        self.assertIn('"--kernel-path" "$KERNEL_PATH"', self.source)
        self.assertIn('"--org-id" "$org_id"', self.source)

    def test_memory_replay_usage_mentions_governed_path(self):
        self.assertIn(
            "Usage: core.sh memory replay SOURCE_REF --target-agent ID",
            self.source,
        )

    def test_memory_latest_artifact_uses_runtime_artifact_paths(self):
        self.assertIn('artifacts/memory/${kind}s/latest.json', self.source)
        self.assertIn('Usage: core.sh memory latest-${kind} [--json]', self.source)

    def test_memory_artifact_history_uses_runtime_artifact_dir(self):
        self.assertIn('artifacts/memory/${kind}s', self.source)
        self.assertIn('Usage: core.sh memory ${kind}-history [LIMIT] [--json]', self.source)

    def test_memory_governance_summary_mentions_operator_summary(self):
        self.assertIn("Usage: core.sh memory governance [LIMIT] [--json]", self.source)
        self.assertIn("[core] memory governance", self.source)

    def test_memory_team_governance_mentions_team_summary(self):
        self.assertIn("Usage: core.sh memory team-governance [LIMIT] [--json]", self.source)
        self.assertIn("/api/team/governed-memory?limit=", self.source)
        self.assertIn("[core] memory team governance", self.source)
        self.assertIn("recent_actions:", self.source)
        self.assertIn("recent_action_count", self.source)

    def test_cmd_memory_does_not_require_active_agent_for_fork_or_replay(self):
        marker = "cmd_memory()"
        start = self.source.find(marker)
        self.assertGreater(start, 0)
        end = self.source.find("\n# ── Command:", start + 1)
        body = self.source[start:end] if end > 0 else self.source[start:]
        receipts_branch = body.find("receipts)")
        global_resolve = body.find('local agent_id; agent_id="$(resolve_agent_id)"')
        self.assertGreater(receipts_branch, 0)
        self.assertGreater(global_resolve, 0)
        self.assertGreater(
            global_resolve,
            receipts_branch,
            "resolve_agent_id should be scoped to receipts branch, not the whole cmd_memory dispatcher",
        )


class TestMemoryRestoreSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_lists_memory_restore(self):
        self.assertIn("memory restore DIR", _help_block(self.source))

    def test_memory_restore_dispatched_from_cmd_memory(self):
        self.assertIn("restore)\n            cmd_memory_restore", self.source)

    def test_memory_restore_function_exists(self):
        self.assertIn("cmd_memory_restore()", self.source)

    def test_memory_restore_supports_agent_filter(self):
        self.assertIn("--agent", self.source)
        self.assertIn('agent_filter="${2:-}"', self.source)

    def test_memory_restore_uses_loom_memory_write_upsert(self):
        # Restore must NOT remove entries; it must upsert via loom memory
        # write. Owner safety rule: non-destructive by default.
        self.assertIn('"memory", "write"', self.source)

    def test_memory_restore_does_not_remove_existing_entries(self):
        # The restore function must not invoke loom memory remove or
        # truncate the runtime memory directories.
        # Find the cmd_memory_restore function body and check it.
        marker = "cmd_memory_restore()"
        start = self.source.find(marker)
        self.assertGreater(start, 0)
        # End at the next top-level function definition.
        end = self.source.find("\n# ── Command:", start + 1)
        body = self.source[start:end] if end > 0 else self.source[start:]
        self.assertNotIn("memory remove", body)
        self.assertNotIn("rm -rf", body)

    def test_memory_restore_requires_manifest(self):
        # Manifest absence must be a hard error, not a silent no-op.
        self.assertIn(
            'die "snapshot manifest missing: $manifest_path"', self.source
        )


class TestMemoryPruneSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_lists_memory_prune(self):
        self.assertIn("memory prune --older-than", _help_block(self.source))

    def test_memory_prune_dispatched_from_cmd_memory(self):
        self.assertIn("prune)\n            cmd_memory_prune", self.source)

    def test_memory_prune_function_exists(self):
        self.assertIn("cmd_memory_prune()", self.source)

    def test_memory_prune_default_mode_is_dry_run(self):
        # Default mode must be dry-run; --execute opts in to deletion.
        self.assertIn('mode="dry-run"', self.source)

    def test_memory_prune_requires_older_than_flag(self):
        self.assertIn(
            'die "Usage: core.sh memory prune --older-than DAYS',
            self.source,
        )

    def test_memory_prune_validates_positive_integer(self):
        # Reject non-integer or zero values for --older-than.
        self.assertIn("--older-than must be a positive integer", self.source)
        self.assertIn("--older-than must be > 0", self.source)

    def test_memory_prune_uses_loom_remove_only_in_execute_mode(self):
        # The function body must guard loom memory remove behind execute mode.
        marker = "cmd_memory_prune()"
        start = self.source.find(marker)
        self.assertGreater(start, 0)
        end = self.source.find("\n# ── Command:", start + 1)
        body = self.source[start:end] if end > 0 else self.source[start:]
        # The dry-run branch must return before the remove loop runs.
        dry_run_branch = body.find('if [ "$mode" = "dry-run" ]; then')
        remove_call = body.find('"$LOOM_BIN" memory remove')
        self.assertGreater(dry_run_branch, 0, "dry-run branch missing")
        self.assertGreater(remove_call, 0, "memory remove call missing")
        self.assertLess(
            dry_run_branch,
            remove_call,
            "dry-run branch must guard the remove call",
        )

    def test_memory_prune_supports_agent_filter(self):
        self.assertIn('agent_filter="${2:-}"', self.source)


class TestMemoryDiffSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_lists_memory_diff(self):
        self.assertIn(
            "memory diff SNAPSHOT_A SNAPSHOT_B",
            _help_block(self.source),
        )

    def test_memory_diff_dispatched_from_cmd_memory(self):
        self.assertIn("diff)\n            cmd_memory_diff", self.source)

    def test_memory_diff_function_exists(self):
        self.assertIn("cmd_memory_diff()", self.source)

    def test_memory_diff_supports_json_output(self):
        # --json is required so dashboards and CI jobs can consume it.
        self.assertIn('output_mode="json"', self.source)
        self.assertIn('"added_count"', self.source)
        self.assertIn('"removed_count"', self.source)
        self.assertIn('"modified_count"', self.source)

    def test_memory_diff_requires_both_snapshots(self):
        # Both positional snapshot dirs are mandatory.
        self.assertIn(
            "Usage: core.sh memory diff SNAPSHOT_A SNAPSHOT_B",
            self.source,
        )

    def test_memory_diff_validates_manifest_presence(self):
        # Each snapshot must carry a valid _manifest.json or fail loud.
        self.assertIn(
            'die "snapshot manifest missing: $left/_manifest.json"',
            self.source,
        )
        self.assertIn(
            'die "snapshot manifest missing: $right/_manifest.json"',
            self.source,
        )

    def test_memory_diff_is_read_only(self):
        # The function must not call any mutating loom subcommand inside
        # its body. Audit/diff is read-only by contract.
        marker = "cmd_memory_diff()"
        start = self.source.find(marker)
        self.assertGreater(start, 0)
        end = self.source.find("\n# ── Command:", start + 1)
        body = self.source[start:end] if end > 0 else self.source[start:]
        self.assertNotIn('"memory", "write"', body)
        self.assertNotIn("memory remove", body)
        self.assertNotIn("memory write", body)
        self.assertNotIn("rm -rf", body)

    def test_memory_diff_exits_nonzero_on_difference(self):
        # Allow operators to branch in CI based on whether anything
        # changed between two snapshots.
        self.assertIn("sys.exit(1)", self.source)


class TestMemoryRotateSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_lists_memory_rotate(self):
        self.assertIn("memory rotate DIR --keep", _help_block(self.source))

    def test_memory_rotate_dispatched_from_cmd_memory(self):
        self.assertIn("rotate)\n            cmd_memory_rotate", self.source)

    def test_memory_rotate_function_exists(self):
        self.assertIn("cmd_memory_rotate()", self.source)

    def test_memory_rotate_default_mode_is_dry_run(self):
        marker = "cmd_memory_rotate()"
        start = self.source.find(marker)
        self.assertGreater(start, 0)
        end = self.source.find("\n# ── Command:", start + 1)
        body = self.source[start:end] if end > 0 else self.source[start:]
        self.assertIn('mode="dry-run"', body)

    def test_memory_rotate_validates_keep_integer(self):
        self.assertIn("--keep must be a non-negative integer", self.source)

    def test_memory_rotate_requires_keep_flag(self):
        self.assertIn(
            "Usage: core.sh memory rotate DIR --keep N",
            self.source,
        )

    def test_memory_rotate_guards_against_directory_traversal(self):
        # Defensive deletion: only rm dirs that contain _manifest.json AND
        # live under the parent_dir we were asked to rotate.
        marker = "cmd_memory_rotate()"
        start = self.source.find(marker)
        end = self.source.find("\n# ── Command:", start + 1)
        body = self.source[start:end] if end > 0 else self.source[start:]
        self.assertIn('[ -f "$path/_manifest.json" ]', body)
        self.assertIn('[[ "$path" == "$parent_dir"/* ]]', body)
        self.assertIn("[fail-guard]", body)

    def test_memory_rotate_uses_recency_ordering(self):
        # snapshot_at_unix descending — most recent first.
        self.assertIn("snapshot_at_unix", self.source)
        self.assertIn("reverse=True", self.source)


class TestMemoryHealthSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_lists_memory_health(self):
        self.assertIn("memory health", _help_block(self.source))

    def test_memory_health_dispatched_from_cmd_memory(self):
        self.assertIn("health)\n            cmd_memory_health", self.source)

    def test_memory_health_function_exists(self):
        self.assertIn("cmd_memory_health()", self.source)

    def test_memory_health_supports_json_alert_top(self):
        self.assertIn("--alert", self.source)
        self.assertIn("--json", self.source)
        self.assertIn("--top", self.source)

    def test_memory_health_validates_top_integer(self):
        self.assertIn("--top must be a non-negative integer", self.source)

    def test_memory_health_is_read_only(self):
        # Health must never call any mutating loom subcommand.
        marker = "cmd_memory_health()"
        start = self.source.find(marker)
        end = self.source.find("\n# ── Command:", start + 1)
        body = self.source[start:end] if end > 0 else self.source[start:]
        self.assertNotIn("memory remove", body)
        self.assertNotIn("memory write", body)
        self.assertNotIn("rm -rf", body)
        # The function must use overview, not search/write/remove.
        self.assertIn("memory overview", body)

    def test_memory_health_alert_mode_exits_nonzero_on_alerts(self):
        # Allow CI / cron jobs to branch on threshold breach.
        marker = "cmd_memory_health()"
        start = self.source.find(marker)
        end = self.source.find("\n# ── Command:", start + 1)
        body = self.source[start:end] if end > 0 else self.source[start:]
        self.assertIn('mode == "alert"', body)
        self.assertIn("sys.exit(2)", body)


if __name__ == "__main__":
    unittest.main()
