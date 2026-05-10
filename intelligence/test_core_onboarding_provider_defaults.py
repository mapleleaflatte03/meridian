#!/usr/bin/env python3
"""Tests for Meridian Core onboarding provider defaults."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
ONBOARD_SH = MERIDIAN_ROOT / "scripts" / "onboard.sh"


class TestOnboardingProviderDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ONBOARD_SH.read_text(encoding="utf-8")

    def test_core_defaults_use_meridian_manager_profile(self):
        self.assertIn("apply_core_brain_defaults()", self.source)
        self.assertIn('MERIDIAN_BRAIN_ROUTE_TYPE="${MERIDIAN_BRAIN_ROUTE_TYPE:-http_json}"', self.source)
        self.assertIn("manager_primary", self.source)
        self.assertIn("grok-4-1-fast-reasoning", self.source)

    def test_core_defaults_do_not_bootstrap_external_cli(self):
        self.assertNotIn("claude_local", self.source)
        self.assertNotIn('MERIDIAN_BRAIN_CLI_BIN:-claude', self.source)
        self.assertNotIn("command -v codex", self.source)
        self.assertNotIn("command -v claude", self.source)

    def test_interactive_prompts_default_to_http_manager(self):
        self.assertIn('Execution route type (http_json / cli_session)" "http_json"', self.source)
        self.assertIn('Execution provider profile" "manager_primary"', self.source)
        self.assertIn('Execution model (blank for provider default)" "grok-4-1-fast-reasoning"', self.source)


if __name__ == "__main__":
    unittest.main()
