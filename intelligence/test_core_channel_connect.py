#!/usr/bin/env python3
"""Tests for Meridian Core channel connect/admin cockpit."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestChannelConnectHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_connect_list(self):
        self.assertIn("channel connect list", self.help_text)

    def test_help_mentions_connect_scaffold(self):
        self.assertIn("channel connect scaffold N T [S]", self.help_text)

    def test_help_mentions_connect_validate(self):
        self.assertIn("channel connect validate ADAPTER", self.help_text)

    def test_help_mentions_connect_scorecard(self):
        self.assertIn("channel connect scorecard", self.help_text)


class TestChannelConnectSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_channel_dispatch_includes_connect(self):
        self.assertIn("cmd_channel_connect", self.source)
        # Tranche 8 adds the `watch` subcommand to the dispatch usage string.
        self.assertIn("channel <list|health|show|deliveries|send|test|diagnostics|proof|verify|watch|connect>", self.source)

    def test_channel_connect_uses_loom_connect_plane(self):
        self.assertIn('"$LOOM_BIN" connect list', self.source)
        self.assertIn('"$LOOM_BIN" connect scaffold', self.source)
        self.assertIn('"$LOOM_BIN" connect validate', self.source)
        self.assertIn('"$LOOM_BIN" connect enable', self.source)
        self.assertIn('"$LOOM_BIN" connect disable', self.source)
        self.assertIn('"$LOOM_BIN" connect test', self.source)
        self.assertIn('"$LOOM_BIN" connect health', self.source)
        self.assertIn('"$LOOM_BIN" connect diagnostics', self.source)
        self.assertIn('"$LOOM_BIN" connect scorecard', self.source)
        self.assertIn('"$LOOM_BIN" connect prune', self.source)


if __name__ == "__main__":
    unittest.main()
