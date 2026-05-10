#!/usr/bin/env python3
"""Tests for Meridian Core session reuse surface."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestSessionReuseSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_reuse(self):
        self.assertIn("session reuse QUERY [--queue|--context]", self.source)
        self.assertIn("/reuse QUERY [--queue|--context]", self.source)

    def test_chat_dispatch_mentions_reuse(self):
        self.assertIn('/reuse\\ *)', self.source)
        self.assertIn('cmd_session reuse $reuse_args', self.source)

    def test_session_reuse_command_exists(self):
        self.assertIn("reuse)", self.source)
        self.assertIn("Usage: core.sh session reuse QUERY [--queue|--context]", self.source)
        self.assertIn("[core] reused context written:", self.source)
        self.assertIn("[core] reused context queued: {queued}", self.source)
        self.assertIn("[core] reused context added to persistent context: {attached}", self.source)

    def test_session_usage_mentions_reuse(self):
        self.assertIn('session <current|use|new|list|show|search|resume|reuse|export|reset|archive>', self.source)


if __name__ == "__main__":
    unittest.main()
