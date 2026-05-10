#!/usr/bin/env python3
"""Tests for Meridian Core persistent context surface."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestContextHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_context_commands(self):
        self.assertIn("context add PATH", self.help_text)
        self.assertIn("context clear", self.help_text)

    def test_help_mentions_no_context_flag(self):
        self.assertIn("--no-context", self.help_text)
        self.assertIn("/context", self.help_text)


class TestContextSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_context_state_file_exists(self):
        self.assertIn('CORE_CONTEXT_FILES_FILE="${CORE_STATE_DIR}/context_files.json"', self.source)

    def test_context_command_dispatch_exists(self):
        self.assertIn('context)     cmd_context "$@" ;;', self.source)
        self.assertIn('cmd_context() {', self.source)

    def test_ask_uses_context_by_default(self):
        self.assertIn('local use_context_files="1"', self.source)
        self.assertIn('--no-context)', self.source)
        self.assertIn("load_context_files_json", self.source)

    def test_chat_mentions_context_surface(self):
        self.assertIn("/context add PATH", self.source)
        self.assertIn('/context\\ add\\ *)', self.source)
        self.assertIn("context files", self.source)


if __name__ == "__main__":
    unittest.main()
