#!/usr/bin/env python3
"""Tests for Meridian Core web/operator bridge surfaces."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestWebBridgeHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_web_urls(self):
        self.assertIn("web urls", self.help_text)

    def test_help_mentions_web_status(self):
        self.assertIn("web status", self.help_text)


class TestWebBridgeSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_main_dispatch_includes_web(self):
        self.assertIn('web)         cmd_web "$@" ;;', self.source)

    def test_web_bridge_mentions_public_surfaces(self):
        self.assertIn("https://app.welliam.codes/", self.source)
        self.assertIn("pilot.html", self.source)
        self.assertIn("demo.html", self.source)

    def test_web_status_probes_gateway_and_workspace(self):
        self.assertIn('/api/healthz', self.source)
        self.assertIn("401 Unauthorized", self.source)
        self.assertIn("ss -ltn", self.source)
        self.assertIn("_port_listening", self.source)
        self.assertIn("MERIDIAN_WORKSPACE_PORT", self.source)
        self.assertIn("MERIDIAN_WORKSPACE_PEER_PORT", self.source)


if __name__ == "__main__":
    unittest.main()
