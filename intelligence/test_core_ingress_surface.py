#!/usr/bin/env python3
"""Tests for Meridian Core ingress operator surface."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestIngressHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_ingress_status(self):
        self.assertIn("ingress status", self.help_text)

    def test_help_mentions_ingress_quarantine_apply(self):
        self.assertIn("ingress quarantine --apply", self.help_text)


class TestIngressSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_render_ingress_snapshot_exists(self):
        self.assertIn("render_ingress_snapshot()", self.source)
        self.assertIn('[core] ingress status', self.source)
        self.assertIn("stale_after_s", self.source)

    def test_ingress_dispatch_exists(self):
        self.assertIn('ingress)     cmd_ingress "$@" ;;', self.source)
        self.assertIn('cmd_ingress() {', self.source)

    def test_ingress_quarantine_apply_reuses_doctor_hygiene(self):
        self.assertIn("quarantine_stale_ingress_requests", self.source)
        self.assertIn("MERIDIAN_CORE_DOCTOR_INGRESS_MAX_AGE_SECONDS", self.source)
        self.assertIn("[core] ingress quarantine", self.source)


if __name__ == "__main__":
    unittest.main()
