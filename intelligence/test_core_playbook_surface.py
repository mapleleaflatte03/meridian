#!/usr/bin/env python3
"""Tests for Meridian Core playbook surface."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestPlaybookHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_playbook_commands(self):
        self.assertIn("playbook list", self.help_text)
        self.assertIn("playbook scaffold NAME", self.help_text)
        self.assertIn("playbook capture NAME", self.help_text)
        self.assertIn("playbook run NAME", self.help_text)
        self.assertIn("playbook every NAME", self.help_text)
        self.assertIn("playbook daily NAME", self.help_text)
        self.assertIn("playbook schedules", self.help_text)
        self.assertIn("playbook run-scheduled", self.help_text)
        self.assertIn("playbook unschedule", self.help_text)


class TestPlaybookSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_playbooks_dir_exists(self):
        self.assertIn('CORE_PLAYBOOKS_DIR="${CORE_STATE_DIR}/playbooks"', self.source)
        self.assertIn('CORE_PLAYBOOK_SCHEDULES_FILE="${CORE_STATE_DIR}/playbook_schedules.json"', self.source)
        self.assertIn("ensure_core_playbooks_dir()", self.source)

    def test_playbook_command_dispatch_exists(self):
        self.assertIn('playbook)    cmd_playbook "$@" ;;', self.source)
        self.assertIn('cmd_playbook() {', self.source)

    def test_playbook_run_uses_core_ask(self):
        self.assertIn('cmd_ask "$combined"', self.source)
        self.assertIn("Execute the following workflow instructions exactly.", self.source)
        self.assertIn("Do not return Meridian/runtime/operator status", self.source)

    def test_playbook_capture_uses_last_output_and_resume(self):
        self.assertIn("capture)", self.source)
        self.assertIn("CORE_LAST_OUTPUT_FILE", self.source)
        self.assertIn("CORE_LAST_RESUME_FILE", self.source)
        self.assertIn("[core] playbook captured:", self.source)

    def test_playbook_schedule_mapping_exists(self):
        self.assertIn("playbook_schedule_job_id()", self.source)
        self.assertIn("playbook_schedule_payload_json()", self.source)
        self.assertIn("save_playbook_schedule_mapping()", self.source)
        self.assertIn("remove_playbook_schedule_mapping()", self.source)
        self.assertIn("remove_loom_playbook_schedule_record()", self.source)
        self.assertIn("refusing to remove non-playbook schedule", self.source)
        self.assertIn('"job_kind": f"playbook:{slug}"', self.source)
        self.assertIn('--job-kind "playbook:${slug}"', self.source)
        self.assertIn("--source-kind core-playbook", self.source)

    def test_playbook_scheduled_run_uses_mapping(self):
        self.assertIn("run-scheduled)", self.source)
        self.assertIn("playbook schedule not found", self.source)
        self.assertIn('cmd_playbook run "$mapped_playbook" "$@"', self.source)

    def test_playbook_unschedule_cleans_mapping(self):
        self.assertIn("unschedule)", self.source)
        self.assertIn("playbook schedule not active in Loom", self.source)
        self.assertIn('remove_loom_playbook_schedule_record "$job_id"', self.source)
        self.assertIn('remove_playbook_schedule_mapping "$job_id"', self.source)


if __name__ == "__main__":
    unittest.main()
