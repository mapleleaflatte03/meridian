#!/usr/bin/env python3
"""Tests for Meridian Core response export materialization."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestResponseExport(unittest.TestCase):
    def test_export_materializes_markdown_heading_file_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loom_root = Path(tmpdir) / "runtime"
            state_dir = loom_root / "state" / "core_cli"
            export_dir = Path(tmpdir) / "export"
            state_dir.mkdir(parents=True, exist_ok=True)

            payload = {
                "recorded_payload": {
                    "session_key": "web_api:test-export",
                    "output": (
                        "### Stack\n"
                        "Python 3.10+\n\n"
                        "### File Tree\n"
                        "```text\n.\n|-- app.py\n```\n\n"
                        "### Complete Code\n"
                        "#### `app.py`\n"
                        "```python\nprint('core-export-ok')\n```\n\n"
                        "### Run Instructions\n"
                        "Run: python app.py\n"
                    ),
                }
            }
            (state_dir / "last_response.json").write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "bash",
                    "-lc",
                    f'MERIDIAN_LOOM_ROOT="{loom_root}" ./scripts/core.sh response export "{export_dir}"',
                ],
                cwd=MERIDIAN_ROOT,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((export_dir / "app.py").exists())
            self.assertIn("core-export-ok", (export_dir / "app.py").read_text(encoding="utf-8"))
            self.assertTrue((export_dir / "_meridian_export_manifest.json").exists())

    def test_export_materializes_plain_markdown_file_blocks_without_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loom_root = Path(tmpdir) / "runtime"
            state_dir = loom_root / "state" / "core_cli"
            export_dir = Path(tmpdir) / "export"
            state_dir.mkdir(parents=True, exist_ok=True)

            payload = {
                "recorded_payload": {
                    "session_key": "web_api:test-export-plain",
                    "output": (
                        "#### `app.py`\n"
                        "```python\nprint(\"core-export-ok\")\n```\n"
                    ),
                }
            }
            (state_dir / "last_response.json").write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "bash",
                    "-lc",
                    f'MERIDIAN_LOOM_ROOT="{loom_root}" ./scripts/core.sh response export "{export_dir}"',
                ],
                cwd=MERIDIAN_ROOT,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((export_dir / "app.py").exists())
            self.assertFalse((export_dir / "artifact.txt").exists())
            self.assertIn("core-export-ok", (export_dir / "app.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
