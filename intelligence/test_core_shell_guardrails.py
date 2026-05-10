#!/usr/bin/env python3
"""Tests for Meridian Core shell presets and research guardrails."""

import subprocess
import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestShellGuardrailHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_shell_list(self):
        self.assertIn("shell list", self.help_text)

    def test_help_mentions_shell_run(self):
        self.assertIn("shell run PRESET", self.help_text)

    def test_help_mentions_research_is_read_only(self):
        self.assertIn('research "cmd [args]"   Run a bounded read-only terminal command', self.help_text)


class TestShellGuardrailSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_dispatch_includes_shell(self):
        self.assertIn('shell)       cmd_shell "$@" ;;', self.source)

    def test_shell_presets_exist(self):
        self.assertIn("repo-status", self.source)
        self.assertIn("repo-diff", self.source)
        self.assertIn("repo-log", self.source)
        self.assertIn("runtime-events", self.source)
        self.assertIn("open-ports", self.source)

    def test_research_guardrails_include_git_and_curl_restrictions(self):
        self.assertIn("git subcommand", self.source)
        self.assertIn("curl flag", self.source)


class TestResearchArgvGuardrails(unittest.TestCase):
    def _run_build_research(self, query: str) -> subprocess.CompletedProcess:
        script = f"""
        set -euo pipefail
        export MERIDIAN_CORE_SH_SOURCE_ONLY=1
        source "{CORE_SH}"
        build_research_argv_json "$1"
        """
        return subprocess.run(
            ["bash", "-c", script, "_", query],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_allows_read_only_git_status(self):
        result = self._run_build_research("git status")
        self.assertEqual(result.returncode, 0)
        self.assertIn('["git", "status"]', result.stdout)

    def test_blocks_git_reset(self):
        result = self._run_build_research("git reset --hard")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed", result.stderr)

    def test_blocks_rm(self):
        result = self._run_build_research("rm -rf /tmp/x")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed", result.stderr)

    def test_blocks_mutating_curl(self):
        result = self._run_build_research("curl -X POST https://example.com")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not allowed", result.stderr)


if __name__ == "__main__":
    unittest.main()
