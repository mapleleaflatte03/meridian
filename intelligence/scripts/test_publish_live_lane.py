#!/usr/bin/env python3
"""Tests for launch publish lane orchestration."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module():
    script_path = (
        Path(__file__).resolve().parents[1]
        / "company"
        / "launch"
        / "publish_live.py"
    )
    spec = importlib.util.spec_from_file_location("publish_live", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load publish script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PublishLiveLaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.launch_dir = self.root / "launch"
        self.artifacts_dir = self.launch_dir / "artifacts"
        self.launch_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.launch_dir / "x_thread.md").write_text(
            "Meridian launch thread body", encoding="utf-8"
        )
        (self.launch_dir / "reddit_llmdevs.md").write_text(
            "Meridian launch post for r/LLMDevs", encoding="utf-8"
        )
        (self.launch_dir / "reddit_localllama.md").write_text(
            "Meridian launch post for r/LocalLLaMA", encoding="utf-8"
        )
        (self.launch_dir / "show_hn_short.md").write_text(
            "Meridian launch note for Show HN", encoding="utf-8"
        )
        (self.launch_dir / "COMMUNITY_MOTION.md").write_text(
            "Meridian community motion update", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_publish_lane_dry_run_success(self) -> None:
        payload = self.module.run_publish_lane(
            launch_dir=self.launch_dir,
            artifact_dir=self.artifacts_dir,
            dry_run=True,
            channels=["x", "reddit", "hn", "discord"],
            site="https://app.welliam.codes",
            fail_on_missing_creds=False,
        )
        self.assertEqual(payload["status"], "ok")
        by_channel = payload["results_by_channel"]
        self.assertEqual(by_channel["x"]["status"], "dry_run")
        self.assertEqual(by_channel["reddit"]["status"], "dry_run")
        self.assertEqual(by_channel["hn"]["status"], "dry_run")
        self.assertEqual(by_channel["discord"]["status"], "dry_run")

        latest = self.artifacts_dir / "publish_live_latest.json"
        self.assertTrue(latest.exists())
        loaded = json.loads(latest.read_text(encoding="utf-8"))
        self.assertEqual(loaded["status"], "ok")

    def test_missing_credentials_fail_in_live_mode(self) -> None:
        payload = self.module.run_publish_lane(
            launch_dir=self.launch_dir,
            artifact_dir=self.artifacts_dir,
            dry_run=False,
            channels=["x", "reddit", "hn", "discord"],
            site="https://app.welliam.codes",
            fail_on_missing_creds=True,
            env={},
        )
        self.assertEqual(payload["status"], "failed")
        failures = payload["failures"]
        self.assertTrue(any(item["channel"] == "x" for item in failures))
        self.assertTrue(any(item["channel"] == "reddit" for item in failures))
        self.assertTrue(any(item["channel"] == "hn" for item in failures))
        self.assertTrue(any(item["channel"] == "discord" for item in failures))

    def test_channel_selection(self) -> None:
        payload = self.module.run_publish_lane(
            launch_dir=self.launch_dir,
            artifact_dir=self.artifacts_dir,
            dry_run=True,
            channels=["discord"],
            site="https://app.welliam.codes",
            fail_on_missing_creds=False,
        )
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(set(payload["results_by_channel"].keys()), {"discord"})

    def test_env_passthrough_for_live_mock(self) -> None:
        payload = self.module.run_publish_lane(
            launch_dir=self.launch_dir,
            artifact_dir=self.artifacts_dir,
            dry_run=False,
            channels=["x"],
            site="https://app.welliam.codes",
            fail_on_missing_creds=False,
            env={"MERIDIAN_X_POST_URL": "http://127.0.0.1:9/invalid", "MERIDIAN_X_API_TOKEN": "token"},
        )
        self.assertEqual(payload["status"], "failed")
        result = payload["results_by_channel"]["x"]
        self.assertEqual(result["status"], "error")
        self.assertIn("network_error", str(result.get("reason", "")))


if __name__ == "__main__":
    unittest.main()
