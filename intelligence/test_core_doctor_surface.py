#!/usr/bin/env python3
"""Tests for Meridian Core doctor receipt and fix surface."""

import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestDoctorHelpText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help_text = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_doctor_fix(self):
        self.assertIn("doctor fix", self.help_text)

    def test_help_mentions_doctor_summary(self):
        self.assertIn("doctor summary", self.help_text)

    def test_help_mentions_doctor_show(self):
        self.assertIn("doctor show", self.help_text)

    def test_help_mentions_doctor_path(self):
        self.assertIn("doctor path", self.help_text)


class TestDoctorSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_core_state_has_last_doctor_file(self):
        self.assertIn('CORE_LAST_DOCTOR_FILE="${CORE_STATE_DIR}/last_doctor.json"', self.source)

    def test_doctor_summary_path_show_exist(self):
        self.assertIn('die "No Core doctor receipt captured yet. Run: ./scripts/core.sh doctor"', self.source)
        self.assertIn('print("[core] doctor summary")', self.source)
        self.assertIn('echo "$CORE_LAST_DOCTOR_FILE"', self.source)
        self.assertIn('print(f"  effective_service: {effective_health}")', self.source)
        self.assertIn('daemon disabled by onboarding policy', self.source)

    def test_doctor_fix_writes_receipt(self):
        self.assertIn('_write_doctor_receipt "fix"', self.source)
        self.assertIn('"service_start"', self.source)
        self.assertIn('"action_results"', self.source)

    def test_doctor_fix_resolves_service_token_fallback(self):
        self.assertIn("resolve_loom_service_token()", self.source)
        self.assertIn("MERIDIAN_LOOM_SERVICE_TOKEN", self.source)
        self.assertIn(".env.gateway", self.source)

    def test_doctor_fix_quarantines_stale_ingress_requests(self):
        self.assertIn("quarantine_stale_ingress_requests()", self.source)
        self.assertIn('"ingress_quarantine"', self.source)
        self.assertIn("/tmp/", self.source)
        self.assertIn("MERIDIAN_CORE_DOCTOR_INGRESS_MAX_AGE_SECONDS", self.source)
        self.assertIn("MERIDIAN_CORE_DOCTOR_SCOPED_INGRESS_MAX_AGE_SECONDS", self.source)
        self.assertIn("submit_action older than", self.source)
        self.assertIn("staged scoped submit_action older than", self.source)

    def test_doctor_fix_clears_stale_stop_marker(self):
        self.assertIn('stop_request_path="${LOOM_ROOT}/run/service/stop.requested"', self.source)
        self.assertIn('"service_clear_stop_request"', self.source)

    def test_doctor_fix_scaffolds_missing_capsule_manifest(self):
        self.assertIn("write_capsule_manifest_scaffold()", self.source)
        self.assertIn('"capsule_manifest_scaffold"', self.source)
        self.assertIn('"label\") or \"\").strip() == \"capsule_manifest\"', self.source)


if __name__ == "__main__":
    unittest.main()
