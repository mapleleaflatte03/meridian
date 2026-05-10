#!/usr/bin/env python3
"""Tests for Meridian Core schedule/routine cockpit."""

import subprocess
import tempfile
import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestScheduleHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_schedule_status(self):
        self.assertIn("schedule status", self.help_text)

    def test_help_mentions_schedule_list(self):
        self.assertIn("schedule list", self.help_text)

    def test_help_mentions_schedule_show(self):
        self.assertIn("schedule show JOB_ID", self.help_text)

    def test_help_mentions_schedule_every(self):
        self.assertIn("schedule every N S", self.help_text)

    def test_help_mentions_schedule_daily(self):
        self.assertIn("schedule daily N T [Z]", self.help_text)

    def test_help_mentions_schedule_run_due(self):
        self.assertIn("schedule run-due [N]", self.help_text)


class TestScheduleSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_core_schedule_uses_loom_schedule_plane(self):
        self.assertIn('"$LOOM_BIN" schedule status', self.source)
        self.assertIn('"$LOOM_BIN" schedule list', self.source)
        self.assertIn('"$LOOM_BIN" schedule show', self.source)
        self.assertIn('"$LOOM_BIN" schedule add', self.source)
        self.assertIn('"$LOOM_BIN" schedule pause', self.source)
        self.assertIn('"$LOOM_BIN" schedule cancel', self.source)
        self.assertIn('"$LOOM_BIN" schedule run', self.source)
        self.assertIn('"$LOOM_BIN" schedule run-due', self.source)

    def test_schedules_command_is_alias_for_schedule_list(self):
        self.assertIn('cmd_schedule list "$@"', self.source)

    def test_legacy_schedule_shorthand_still_routes_to_interval_creation(self):
        self.assertIn('cmd_schedule_every "$@"', self.source)


class TestScheduleJobIdSlug(unittest.TestCase):
    def _run_slug(self, value: str) -> str:
        script = f"""
        set -euo pipefail
        eval "$(sed -n '/^schedule_job_id_slug/,/^}}/p' "{CORE_SH}")"
        schedule_job_id_slug "$1"
        """
        result = subprocess.run(
            ["bash", "-c", script, "_", value],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            self.fail(result.stderr)
        return result.stdout.strip()

    def test_slug_normalizes_name(self):
        self.assertEqual(self._run_slug("Morning Brief"), "morning-brief")

    def test_slug_falls_back_for_empty_name(self):
        self.assertEqual(self._run_slug("   "), "core-routine")


if __name__ == "__main__":
    unittest.main()
