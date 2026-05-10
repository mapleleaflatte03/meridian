#!/usr/bin/env python3
"""Tests for Meridian Core persistent file queue surface."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestFilesHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_files_commands(self):
        self.assertIn("files add PATH", self.help_text)
        self.assertIn("files clear", self.help_text)

    def test_help_mentions_queued_files_ask(self):
        self.assertIn("ask --queued-files", self.help_text)
        self.assertIn("/use-files", self.help_text)
        self.assertIn("/save-files", self.help_text)


class TestFilesSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_pending_files_state_file_exists(self):
        self.assertIn('CORE_PENDING_FILES_FILE="${CORE_STATE_DIR}/pending_files.json"', self.source)

    def test_files_command_dispatch_exists(self):
        self.assertIn('files)       cmd_files "$@" ;;', self.source)
        self.assertIn('cmd_files() {', self.source)

    def test_ask_can_use_queued_files(self):
        self.assertIn("--queued-files|--files)", self.source)
        self.assertIn('use_queued_files="1"', self.source)
        self.assertIn("load_pending_files_json", self.source)

    def test_chat_can_use_and_save_persistent_files(self):
        self.assertIn("/use-files", self.source)
        self.assertIn("/save-files", self.source)
        self.assertIn('save_pending_files_json "$save_json"', self.source)


if __name__ == "__main__":
    unittest.main()
