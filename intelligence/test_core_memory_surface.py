#!/usr/bin/env python3
"""Tests for Meridian Core memory recall surface.

Covers:
- core.sh memory search subcommand wiring and dispatch
- core.sh recall accepts --text and --limit flags
- Help text exposes search and recall options
- Cross-agent fan-out flag is wired and renders [agent/category] rows
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


if __name__ == "__main__":
    unittest.main()
