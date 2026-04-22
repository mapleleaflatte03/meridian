#!/usr/bin/env python3
import unittest
from unittest import mock

import capsule


class CapsuleTests(unittest.TestCase):
    def test_resolve_org_id_accepts_explicit_host_bound_org_id_when_registry_is_missing_it(self):
        with mock.patch.object(capsule, "_load_orgs", return_value={"org_meridian": {"slug": "meridian"}}):
            self.assertEqual(capsule.resolve_org_id("org_hostbound123"), "org_hostbound123")

    def test_capsule_dir_falls_back_to_host_bound_legacy_economy_when_dedicated_capsule_is_missing(self):
        with mock.patch.object(capsule, "_load_orgs", return_value={"org_meridian": {"slug": "meridian"}}):
            with mock.patch.object(capsule, "LEGACY_LEDGER_FILE", "/tmp/legacy-ledger.json"):
                with mock.patch("capsule.os.path.exists", side_effect=lambda path: path == "/tmp/legacy-ledger.json"):
                    with mock.patch("capsule.os.path.isdir", return_value=False):
                        self.assertEqual(capsule.capsule_dir("org_hostbound123"), capsule.ECONOMY_DIR)


if __name__ == "__main__":
    unittest.main()
