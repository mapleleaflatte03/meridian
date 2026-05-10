#!/usr/bin/env python3
"""Tests for Meridian Core session search surface."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestSessionSearchSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_session_help_mentions_search(self):
        self.assertIn("session search QUERY", self.source)
        self.assertIn("/search QUERY", self.source)

    def test_chat_dispatch_mentions_search(self):
        self.assertIn('/search\\ *)', self.source)
        self.assertIn('cmd_session search "${line#"/search "}"', self.source)

    def test_session_search_command_exists(self):
        self.assertIn("search)", self.source)
        self.assertIn('Usage: core.sh session search QUERY [LIMIT]', self.source)
        self.assertIn('[core] session search: {query}', self.source)
        self.assertIn('state", "session-history", "events"', self.source)

    def test_session_usage_mentions_search(self):
        self.assertIn('session <current|use|new|list|show|search|resume|reuse|export|reset|archive>', self.source)


if __name__ == "__main__":
    unittest.main()
