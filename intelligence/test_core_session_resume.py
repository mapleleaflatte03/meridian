#!/usr/bin/env python3
"""Tests for Meridian Core session resume surface."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestSessionResumeSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_resume(self):
        self.assertIn("session resume SESSION_KEY EVENT_INDEX [--queue|--context]", self.source)
        self.assertIn("/resume SESSION_KEY EVENT_INDEX [--queue|--context]", self.source)
        self.assertIn("/use-resume", self.source)

    def test_session_resume_command_exists(self):
        self.assertIn('CORE_LAST_RESUME_FILE="${CORE_STATE_DIR}/last_resume.txt"', self.source)
        self.assertIn("Usage: core.sh session resume SESSION_KEY EVENT_INDEX [--queue|--context]", self.source)
        self.assertIn("[core] resumed context written:", self.source)

    def test_chat_dispatch_mentions_resume(self):
        self.assertIn('/resume\\ *)', self.source)
        self.assertIn('cmd_session resume $resume_args', self.source)
        self.assertIn('/use-resume)', self.source)
        self.assertIn('[core] resumed context loaded', self.source)

    def test_resume_queue_bridge_exists(self):
        self.assertIn('queue_after="1"', self.source)
        self.assertIn('context_after="1"', self.source)
        self.assertIn('[core] resumed context queued: {queued}', self.source)
        self.assertIn('[core] resumed context added to persistent context: {attached}', self.source)
        self.assertIn('save_pending_files_json "$merged_json"', self.source)
        self.assertIn('save_context_files_json "$merged_context_json"', self.source)

    def test_session_usage_mentions_resume(self):
        self.assertIn('session <current|use|new|list|show|search|resume|reuse|export|reset|archive>', self.source)


if __name__ == "__main__":
    unittest.main()
