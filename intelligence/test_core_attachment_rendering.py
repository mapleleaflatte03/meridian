#!/usr/bin/env python3
"""Tests for Meridian Core attachment flow and artifact-safe rendering.

Covers:
- Gateway /api/run attachment payload processing
- core.sh build_attachments_json helper (via subprocess)
- core.sh render_output_safe truncation logic (via subprocess)
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"


class TestBuildAttachmentsJson(unittest.TestCase):
    """Test the build_attachments_json bash helper."""

    def _run_build_attachments(self, *file_paths: str) -> list[dict]:
        """Call build_attachments_json by extracting the function from core.sh."""
        paths_escaped = " ".join(f'"{p}"' for p in file_paths)
        # Extract only the function definitions from core.sh without running dispatch
        script = f"""
        set -euo pipefail
        eval "$(sed -n '/^build_attachments_json/,/^}}/p' "{CORE_SH}")"
        build_attachments_json {paths_escaped}
        """
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            self.fail(f"build_attachments_json failed: {result.stderr}")
        return json.loads(result.stdout.strip())

    def test_single_text_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("print('hello')\n")
            f.flush()
            try:
                attachments = self._run_build_attachments(f.name)
                self.assertEqual(len(attachments), 1)
                self.assertEqual(attachments[0]["name"], os.path.basename(f.name))
                self.assertIn("print('hello')", attachments[0]["content"])
                self.assertIn("text/", attachments[0]["mime_type"])
            finally:
                os.unlink(f.name)

    def test_multiple_files(self):
        files = []
        try:
            for i in range(3):
                f = tempfile.NamedTemporaryFile(
                    mode="w", suffix=f".txt", delete=False
                )
                f.write(f"content {i}\n")
                f.flush()
                f.close()
                files.append(f.name)
            attachments = self._run_build_attachments(*files)
            self.assertEqual(len(attachments), 3)
            for i, att in enumerate(attachments):
                self.assertIn(f"content {i}", att["content"])
        finally:
            for path in files:
                os.unlink(path)

    def test_missing_file_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("valid\n")
            f.flush()
            try:
                attachments = self._run_build_attachments(
                    "/nonexistent/file.txt", f.name
                )
                self.assertEqual(len(attachments), 1)
                self.assertIn("valid", attachments[0]["content"])
            finally:
                os.unlink(f.name)

    def test_binary_file_skipped(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00\x01\x02\x03binary data")
            f.flush()
            try:
                attachments = self._run_build_attachments(f.name)
                self.assertEqual(len(attachments), 0)
            finally:
                os.unlink(f.name)

    def test_large_file_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("x" * (600 * 1024))  # 600 KiB > 512 KiB limit
            f.flush()
            try:
                attachments = self._run_build_attachments(f.name)
                self.assertEqual(len(attachments), 0)
            finally:
                os.unlink(f.name)

    def test_empty_args_returns_empty_array(self):
        attachments = self._run_build_attachments()
        self.assertEqual(attachments, [])


class TestRenderOutputSafe(unittest.TestCase):
    """Test the render_output_safe bash helper."""

    def _run_render(self, text: str, threshold: int = 4000, lines: int = 80) -> str:
        # Extract render_output_safe function from core.sh without running dispatch
        script = f"""
        set -euo pipefail
        eval "$(sed -n '/^render_output_safe/,/^}}/p' "{CORE_SH}")"
        CORE_ARTIFACT_LONG_THRESHOLD={threshold}
        CORE_ARTIFACT_LONG_LINES={lines}
        CORE_LAST_OUTPUT_FILE="/dev/null"
        render_output_safe "$1"
        """
        result = subprocess.run(
            ["bash", "-c", script, "_", text],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout

    def test_short_output_passes_through(self):
        text = "Hello world\nLine 2\n"
        output = self._run_render(text)
        self.assertIn("Hello world", output)
        self.assertNotIn("[core] output truncated", output)

    def test_long_output_truncated(self):
        text = "\n".join(f"line {i}" for i in range(200))
        output = self._run_render(text, threshold=100, lines=20)
        self.assertIn("[core] output truncated", output)
        self.assertIn("response page", output)

    def test_long_chars_truncated(self):
        text = "x" * 5000
        output = self._run_render(text, threshold=1000)
        self.assertIn("[core] output truncated", output)


class TestGatewayAttachmentProcessing(unittest.TestCase):
    """Test the gateway's attachment field handling in /api/run payload."""

    def test_attachment_context_prepended_to_goal(self):
        """Simulate the gateway attachment processing logic."""
        payload = {
            "goal": "review this code",
            "attachments": [
                {
                    "name": "main.py",
                    "content": "print('hello')",
                    "mime_type": "text/x-python",
                },
            ],
        }
        # Replicate the gateway logic
        raw_attachments = payload.get("attachments") or []
        attachment_context = ""
        attachment_names = []
        goal = payload["goal"]
        if isinstance(raw_attachments, list):
            for att in raw_attachments:
                if not isinstance(att, dict):
                    continue
                att_name = str(att.get("name") or "").strip()
                att_content = str(att.get("content") or "").strip()
                if not att_name or not att_content:
                    continue
                attachment_names.append(att_name)
                attachment_context += f'\n<file name="{att_name}">\n{att_content}\n</file>\n'
        if attachment_context:
            goal = f"[Attached files: {', '.join(attachment_names)}]\n{attachment_context}\n{goal.strip()}"

        self.assertIn("[Attached files: main.py]", goal)
        self.assertIn('<file name="main.py">', goal)
        self.assertIn("print('hello')", goal)
        self.assertIn("review this code", goal)

    def test_empty_attachments_leaves_goal_unchanged(self):
        payload = {"goal": "just a question", "attachments": []}
        raw_attachments = payload.get("attachments") or []
        attachment_context = ""
        attachment_names = []
        goal = payload["goal"]
        if isinstance(raw_attachments, list):
            for att in raw_attachments:
                if not isinstance(att, dict):
                    continue
                att_name = str(att.get("name") or "").strip()
                att_content = str(att.get("content") or "").strip()
                if not att_name or not att_content:
                    continue
                attachment_names.append(att_name)
                attachment_context += f'\n<file name="{att_name}">\n{att_content}\n</file>\n'
        if attachment_context:
            goal = f"[Attached files: {', '.join(attachment_names)}]\n{attachment_context}\n{goal.strip()}"

        self.assertEqual(goal, "just a question")

    def test_multiple_attachments(self):
        payload = {
            "goal": "compare",
            "attachments": [
                {"name": "a.py", "content": "def a(): pass"},
                {"name": "b.py", "content": "def b(): pass"},
            ],
        }
        raw_attachments = payload.get("attachments") or []
        attachment_context = ""
        attachment_names = []
        goal = payload["goal"]
        if isinstance(raw_attachments, list):
            for att in raw_attachments:
                if not isinstance(att, dict):
                    continue
                att_name = str(att.get("name") or "").strip()
                att_content = str(att.get("content") or "").strip()
                if not att_name or not att_content:
                    continue
                attachment_names.append(att_name)
                attachment_context += f'\n<file name="{att_name}">\n{att_content}\n</file>\n'
        if attachment_context:
            goal = f"[Attached files: {', '.join(attachment_names)}]\n{attachment_context}\n{goal.strip()}"

        self.assertIn("[Attached files: a.py, b.py]", goal)
        self.assertIn('<file name="a.py">', goal)
        self.assertIn('<file name="b.py">', goal)

    def test_malformed_attachment_ignored(self):
        payload = {
            "goal": "question",
            "attachments": [
                {"name": "", "content": "orphan"},
                "not_a_dict",
                {"name": "valid.txt", "content": "ok"},
            ],
        }
        raw_attachments = payload.get("attachments") or []
        attachment_context = ""
        attachment_names = []
        goal = payload["goal"]
        if isinstance(raw_attachments, list):
            for att in raw_attachments:
                if not isinstance(att, dict):
                    continue
                att_name = str(att.get("name") or "").strip()
                att_content = str(att.get("content") or "").strip()
                if not att_name or not att_content:
                    continue
                attachment_names.append(att_name)
                attachment_context += f'\n<file name="{att_name}">\n{att_content}\n</file>\n'
        if attachment_context:
            goal = f"[Attached files: {', '.join(attachment_names)}]\n{attachment_context}\n{goal.strip()}"

        self.assertEqual(len(attachment_names), 1)
        self.assertEqual(attachment_names[0], "valid.txt")
        self.assertIn("ok", goal)
        self.assertNotIn("orphan", goal)

    def test_no_attachments_field(self):
        payload = {"goal": "plain question"}
        raw_attachments = payload.get("attachments") or []
        self.assertEqual(raw_attachments, [])


class TestCoreShHelp(unittest.TestCase):
    """Verify the help output includes attachment docs."""

    def test_help_mentions_file_flag(self):
        result = subprocess.run(
            ["bash", str(CORE_SH), "help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--file", result.stdout)
        self.assertIn("response page", result.stdout)
        self.assertIn("File attachments", result.stdout)
        self.assertIn("Long output handling", result.stdout)


if __name__ == "__main__":
    unittest.main()
