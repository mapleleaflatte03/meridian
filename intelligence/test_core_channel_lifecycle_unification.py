#!/usr/bin/env python3
"""Tests for Meridian Tranche 8: telegram lifecycle unification + auto-recipient + channel watch.

Covers:
- _recent_active_peer helper: empty, fresh, multi-channel filtering, age cutoff.
- _verify_channel_round_trip with recipient='auto': auto-resolution and
  rejection when no peer exists.
- TelegramAdapter poll/drain wires lifecycle on 409 conflict and exceptions.
- core.sh: watch/verify dispatch wiring, _resolve_recent_active_peer helper.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
INTEL = Path(__file__).resolve().parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"
GATEWAY_PY = INTEL / "meridian_gateway.py"


# ── Source surface tests ───────────────────────────────────────────────────


class GatewaySourceSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")

    def test_recent_active_peer_helper_defined(self):
        self.assertIn("def _recent_active_peer(", self.source)

    def test_verify_supports_auto_recipient(self):
        self.assertIn('recipient.lower() in {"auto", "*"}', self.source)
        self.assertIn("_recent_active_peer(channel_id)", self.source)

    def test_verify_returns_auto_resolved_field(self):
        self.assertIn('"auto_resolved_recipient"', self.source)

    def test_telegram_poll_409_records_lifecycle_failure(self):
        self.assertIn("poll conflict: another poller owns the bot token", self.source)

    def test_telegram_poll_http_error_records_lifecycle_failure(self):
        self.assertIn("poll http {exc.code}", self.source)

    def test_telegram_poll_generic_records_lifecycle_failure(self):
        self.assertIn('f"poll: {exc.__class__.__name__}: {exc}"', self.source)

    def test_telegram_drain_records_lifecycle_failure(self):
        self.assertIn('f"drain: {exc.__class__.__name__}: {exc}"', self.source)


class CoreShellSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_watch_subcommand_dispatched(self):
        self.assertIn("watch)\n            cmd_channel_watch", self.source)

    def test_watch_function_defined(self):
        self.assertIn("cmd_channel_watch()", self.source)

    def test_resolve_recent_active_peer_helper_defined(self):
        self.assertIn("_resolve_recent_active_peer()", self.source)

    def test_verify_defaults_to_auto(self):
        self.assertIn('recipient="auto"', self.source)

    def test_watch_in_dispatch_usage_string(self):
        self.assertIn("|watch|", self.source)

    def test_watch_documented_in_help(self):
        self.assertIn("channel watch CH", self.source)


# ── Importable function tests ──────────────────────────────────────────────


if str(INTEL) not in sys.path:
    sys.path.insert(0, str(INTEL))

import test_gateway_brain_router as _tgbr  # noqa: E402
_mg = _tgbr.meridian_gateway


def _write_inbox(tmp: Path, channel_id: str, peer: str, ingress_id: str, ts_ms: int):
    inbox_dir = tmp / "state" / "channels" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "channel_id": channel_id,
        "peer_id": peer,
        "ingress_id": ingress_id,
        "received_at_unix_ms": ts_ms,
        "text": "hello",
    }
    (inbox_dir / f"{ts_ms}-{ingress_id}.json").write_text(json.dumps(rec), encoding="utf-8")
    return rec


class RecentActivePeerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="meridian-recent-peer-test-"))
        self._orig_root = _mg.LOOM_ROOT
        _mg.LOOM_ROOT = str(self.tmp)

    def tearDown(self):
        _mg.LOOM_ROOT = self._orig_root
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_inbox_returns_empty(self):
        self.assertEqual(_mg._recent_active_peer("telegram"), "")

    def test_picks_most_recent_peer(self):
        import time
        now_ms = int(time.time() * 1000)
        _write_inbox(self.tmp, "telegram", "peer-1", "i1", now_ms - 3000)
        _write_inbox(self.tmp, "telegram", "peer-2", "i2", now_ms - 1000)
        _write_inbox(self.tmp, "telegram", "peer-3", "i3", now_ms - 2000)
        self.assertEqual(_mg._recent_active_peer("telegram"), "peer-2")

    def test_filters_by_channel(self):
        import time
        now_ms = int(time.time() * 1000)
        _write_inbox(self.tmp, "telegram", "tg-peer", "i1", now_ms - 5000)
        _write_inbox(self.tmp, "zalo", "zalo-peer", "i2", now_ms - 1000)
        self.assertEqual(_mg._recent_active_peer("telegram"), "tg-peer")
        self.assertEqual(_mg._recent_active_peer("zalo"), "zalo-peer")

    def test_age_cutoff_excludes_old_records(self):
        import time
        old_ms = int((time.time() - 10 * 86400) * 1000)
        _write_inbox(self.tmp, "telegram", "old-peer", "i1", old_ms)
        # max_age_seconds=3600 → only last hour
        self.assertEqual(_mg._recent_active_peer("telegram", max_age_seconds=3600), "")
        # max_age_seconds=0 disables the cutoff, returns the old peer
        self.assertEqual(_mg._recent_active_peer("telegram", max_age_seconds=0), "old-peer")

    def test_skips_records_without_peer_id(self):
        inbox_dir = self.tmp / "state" / "channels" / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        bad = {"channel_id": "telegram", "peer_id": "", "received_at_unix_ms": 9999}
        (inbox_dir / "9999-bad.json").write_text(json.dumps(bad), encoding="utf-8")
        self.assertEqual(_mg._recent_active_peer("telegram"), "")

    def test_unknown_channel_returns_empty(self):
        self.assertEqual(_mg._recent_active_peer(""), "")


class VerifyAutoRecipientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="meridian-verify-auto-test-"))
        (self.tmp / "state" / "channels" / "delivery").mkdir(parents=True)
        self._orig_root = _mg.LOOM_ROOT
        _mg.LOOM_ROOT = str(self.tmp)

    def tearDown(self):
        _mg.LOOM_ROOT = self._orig_root
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_auto_rejects_when_no_peer(self):
        result = _mg._verify_channel_round_trip("telegram", "auto", "hi", timeout_seconds=1.0)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("no recent active peer", result["reason"])

    def test_auto_resolves_to_recent_peer(self):
        _write_inbox(self.tmp, "telegram", "auto-peer-99", "i1", 5_000_000_000_000)

        captured = {}

        def fake_send(channel, recipient, text):
            captured["recipient"] = recipient
            return {"ok": False, "error": "no real loom in test"}

        with mock.patch.object(_mg, "_loom_channel_send", side_effect=fake_send):
            result = _mg._verify_channel_round_trip("telegram", "auto", "probe", timeout_seconds=1.0)

        self.assertEqual(result["status"], "submission_failed")
        self.assertEqual(captured["recipient"], "auto-peer-99")
        # The result records the resolved recipient and the auto flag
        self.assertEqual(result["recipient"], "auto-peer-99")

    def test_star_recipient_also_resolves(self):
        _write_inbox(self.tmp, "telegram", "star-peer", "i1", 6_000_000_000_000)
        with mock.patch.object(_mg, "_loom_channel_send", return_value={"ok": False}):
            result = _mg._verify_channel_round_trip("telegram", "*", "probe", timeout_seconds=1.0)
        self.assertEqual(result["status"], "submission_failed")
        self.assertEqual(result["recipient"], "star-peer")


if __name__ == "__main__":
    unittest.main()
