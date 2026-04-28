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


if __name__ == "__main__":
    unittest.main()
