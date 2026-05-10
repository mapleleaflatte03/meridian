#!/usr/bin/env python3
"""Tests for Meridian Core browse restrictions and host allowlists."""

import os
import subprocess
import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestBrowsePolicyHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_browse_policy(self):
        self.assertIn("web browse-policy", self.help_text)

    def test_help_mentions_browse_allowlist_config(self):
        self.assertIn("MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS", self.help_text)


class TestBrowsePolicySourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_browse_validates_url(self):
        self.assertIn('validate_browse_url "$url"', self.source)

    def test_browse_policy_exposed_in_web_command(self):
        self.assertIn("browse-policy", self.source)

    def test_config_allowlist_contains_browse_hosts(self):
        self.assertIn("MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS", self.source)


class TestBrowseValidationHelper(unittest.TestCase):
    def _run_validate(self, url: str, allowlist: str = "") -> subprocess.CompletedProcess:
        script = f"""
        set -euo pipefail
        export MERIDIAN_CORE_SH_SOURCE_ONLY=1
        export MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS="$2"
        source "{CORE_SH}"
        validate_browse_url "$1"
        """
        return subprocess.run(
            ["bash", "-c", script, "_", url, allowlist],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_allows_https_without_allowlist(self):
        result = self._run_validate("https://app.welliam.codes/pilot.html")
        self.assertEqual(result.returncode, 0)

    def test_blocks_file_scheme(self):
        result = self._run_validate("file:///etc/passwd")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("http/https only", result.stderr)

    def test_blocks_host_outside_allowlist(self):
        result = self._run_validate("https://example.com", "app.welliam.codes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not in MERIDIAN_CORE_BROWSE_ALLOWED_HOSTS", result.stderr)

    def test_allows_subdomain_inside_allowlist(self):
        result = self._run_validate("https://docs.app.welliam.codes", "app.welliam.codes")
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
