import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RESTORE_PATH = os.path.join(THIS_DIR, "migration_restore.py")
SPEC = importlib.util.spec_from_file_location("meridian_migration_restore", RESTORE_PATH)
restore = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = restore
SPEC.loader.exec_module(restore)


class MigrationRestoreTests(unittest.TestCase):
    def test_collect_reads_bundle_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            target = bundle_dir / "target.txt"
            target.write_text("hello", encoding="utf-8")
            manifest = [{
                "path": str(target),
                "exists": True,
                "type": "file",
                "size_bytes": target.stat().st_size,
                "kind": "test_file",
            }]
            (bundle_dir / "state-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with tarfile.open(bundle_dir / "state-bundle.tar.gz", "w:gz"):
                pass

            payload = restore.collect(bundle_dir)
            self.assertEqual(payload["manifest_summary"]["entry_count"], 1)
            self.assertTrue(payload["verify"]["ok"])

    def test_extract_archive_rejects_unsafe_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "bad.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                info = tarfile.TarInfo("../escape.txt")
                data = b"bad"
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

            with self.assertRaises(ValueError):
                restore.extract_archive(archive_path, dry_run=True)

    def test_restore_dry_run_skips_service_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            manifest = []
            (bundle_dir / "state-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with tarfile.open(bundle_dir / "state-bundle.tar.gz", "w:gz"):
                pass

            with patch.object(restore, "_run") as mocked_run:
                payload = restore.restore(
                    bundle_dir,
                    stop_services=True,
                    start_services=True,
                    dry_run=True,
                )
            self.assertFalse(mocked_run.called)
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["archive_restore"]["restored"], False)


if __name__ == "__main__":
    unittest.main()
