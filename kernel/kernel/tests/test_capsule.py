#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "capsule.py"
SPEC = importlib.util.spec_from_file_location("kernel_capsule", MODULE_PATH)
capsule = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capsule)


class CapsuleTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix="meridian-capsule-test-")
        self.root = pathlib.Path(self.tmpdir.name)
        self.economy_dir = self.root / "economy"
        self.capsules_dir = self.root / "capsules"
        self.kernel_dir = self.root / "kernel"
        self.economy_dir.mkdir()
        self.capsules_dir.mkdir()
        self.kernel_dir.mkdir()
        (self.economy_dir / "ledger.json").write_text("{}")

        self.orig_economy_dir = capsule.ECONOMY_DIR
        self.orig_capsules_dir = capsule.CAPSULES_DIR
        self.orig_orgs_file = capsule.ORGS_FILE
        self.orig_aliases = dict(capsule._CAPSULE_ALIASES)

        capsule.ECONOMY_DIR = str(self.economy_dir)
        capsule.CAPSULES_DIR = str(self.capsules_dir)
        capsule.ORGS_FILE = str(self.kernel_dir / "organizations.json")
        capsule._CAPSULE_ALIASES.clear()

    def tearDown(self):
        capsule.ECONOMY_DIR = self.orig_economy_dir
        capsule.CAPSULES_DIR = self.orig_capsules_dir
        capsule.ORGS_FILE = self.orig_orgs_file
        capsule._CAPSULE_ALIASES.clear()
        capsule._CAPSULE_ALIASES.update(self.orig_aliases)
        self.tmpdir.cleanup()

    def _write_orgs(self, orgs):
        with open(capsule.ORGS_FILE, "w") as f:
            json.dump({"organizations": orgs}, f)

    def test_register_capsule_alias_overrides_path_resolution(self):
        target = self.root / "legacy"
        target.mkdir()
        capsule.register_capsule_alias("org_demo", str(target))
        self.assertEqual(
            capsule.capsule_path("org_demo", "ledger.json"),
            str(target / "ledger.json"),
        )
        self.assertEqual(capsule.capsule_dir("org_demo"), str(target))

    def test_auto_aliases_single_legacy_org_to_economy(self):
        self._write_orgs({
            "org_demo": {
                "id": "org_demo",
                "slug": "demo-org",
                "treasury_id": None,
            }
        })
        self.assertEqual(
            capsule.capsule_path("org_demo", "ledger.json"),
            str(self.economy_dir / "ledger.json"),
        )
        self.assertEqual(capsule.capsule_dir("org_demo"), str(self.economy_dir))

    def test_does_not_alias_when_multiple_orgs_have_no_capsule(self):
        self._write_orgs({
            "org_a": {"id": "org_a", "slug": "a", "treasury_id": None},
            "org_b": {"id": "org_b", "slug": "b", "treasury_id": None},
        })
        self.assertEqual(
            capsule.capsule_path("org_a", "ledger.json"),
            str(self.capsules_dir / "org_a" / "ledger.json"),
        )
        self.assertNotIn("org_a", capsule._CAPSULE_ALIASES)

    def test_list_capsules_includes_legacy_alias_candidate(self):
        self._write_orgs({
            "org_demo": {
                "id": "org_demo",
                "slug": "demo-org",
                "treasury_id": None,
            }
        })
        self.assertEqual(capsule.list_capsules(), ["org_demo"])

    def test_init_capsule_seeds_updated_at_field(self):
        self._write_orgs({})
        capsule.init_capsule("org_new")
        ledger = json.loads((self.capsules_dir / "org_new" / "ledger.json").read_text())
        self.assertIn("updatedAt", ledger)


if __name__ == "__main__":
    unittest.main()
