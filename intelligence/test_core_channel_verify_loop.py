#!/usr/bin/env python3
"""Tests for Meridian Tranche 7: channel verify round trip + telegram polling state surface.

Covers:
- _verify_channel_round_trip: rejection paths, submission_failed path,
  delivered path, timeout path, chain extension, schema version.
- /api/channels/{id}/verify endpoint dispatch wiring.
- Multi-channel health surfaces telegram polling_state via poll_state.
- core.sh channel verify wiring, dispatch, helpers.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
INTEL = Path(__file__).resolve().parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"
GATEWAY_PY = INTEL / "meridian_gateway.py"


# ── Source-level surface tests ─────────────────────────────────────────────


class GatewaySourceSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")

    def test_verify_helper_defined(self):
        self.assertIn("def _verify_channel_round_trip(", self.source)

    def test_verify_returns_schema_version(self):
        self.assertIn('"meridian.channels.verify.v1"', self.source)

    def test_verify_endpoint_registered(self):
        self.assertIn('request_path.endswith("/verify")', self.source)

    def test_verify_endpoint_calls_helper(self):
        self.assertIn("_verify_channel_round_trip(", self.source)

    def test_health_surfaces_telegram_polling_state(self):
        self.assertIn('hasattr(a, "polling_state")', self.source)

    def test_health_uses_polling_conflict_detail(self):
        self.assertIn("polling_conflict_detail", self.source)


class CoreShellSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_verify_subcommand_dispatched(self):
        self.assertIn("verify)\n            cmd_channel_verify", self.source)

    def test_verify_function_defined(self):
        self.assertIn("cmd_channel_verify()", self.source)

    def test_verify_local_runner_defined(self):
        self.assertIn("_run_local_channel_verify()", self.source)

    def test_compute_chain_head_helper_defined(self):
        self.assertIn("_compute_chain_head_for_channel()", self.source)

    def test_verify_documented_in_usage(self):
        self.assertIn("channel verify CH R [T]", self.source)

    def test_verify_in_dispatch_usage_string(self):
        self.assertIn("|verify|", self.source)


# ── Importable function tests ──────────────────────────────────────────────


if str(INTEL) not in sys.path:
    sys.path.insert(0, str(INTEL))

import test_gateway_brain_router as _tgbr  # noqa: E402
_mg = _tgbr.meridian_gateway


def _make_terminal_record(tmp: Path, channel_id: str, delivery_id: str, status: str, submitted_ms: int):
    delivery_dir = tmp / "state" / "channels" / "delivery"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "channel_id": channel_id,
        "delivery_id": delivery_id,
        "status": status,
        "recipient": "5555",
        "submitted_at_unix_ms": submitted_ms,
        "completed_at_unix_ms": submitted_ms + 50,
        "external_ref": f"ext-{delivery_id}",
        "status_detail": "",
    }
    (delivery_dir / f"{submitted_ms}-{delivery_id}.json").write_text(json.dumps(rec), encoding="utf-8")
    return rec


class VerifyHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="meridian-verify-test-"))
        (self.tmp / "state" / "channels" / "delivery").mkdir(parents=True)
        self._orig_root = _mg.LOOM_ROOT
        _mg.LOOM_ROOT = str(self.tmp)

    def tearDown(self):
        _mg.LOOM_ROOT = self._orig_root
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rejected_unknown_channel(self):
        result = _mg._verify_channel_round_trip("not-a-channel", "r", "hi")
        self.assertEqual(result["status"], "rejected")
        self.assertIn("unknown channel", result["reason"])
        self.assertEqual(result["schema_version"], "meridian.channels.verify.v1")

    def test_rejected_missing_recipient(self):
        result = _mg._verify_channel_round_trip("telegram", "", "hi")
        self.assertEqual(result["status"], "rejected")
        self.assertIn("recipient", result["reason"])

    def test_rejected_missing_text(self):
        result = _mg._verify_channel_round_trip("telegram", "1234", "")
        self.assertEqual(result["status"], "rejected")

    def test_submission_failed_when_send_returns_no_delivery_id(self):
        with mock.patch.object(_mg, "_loom_channel_send", return_value={"ok": False, "error": "boom"}):
            result = _mg._verify_channel_round_trip("telegram", "1234", "hi", timeout_seconds=1.0)
        self.assertEqual(result["status"], "submission_failed")
        self.assertEqual(result["recipient"], "1234")
        self.assertIn("boom", result.get("submit_error", ""))
        self.assertIn("pre_head_chain_hash", result)

    def test_delivered_extends_chain(self):
        # Pre-existing record so pre_head is non-empty
        _make_terminal_record(self.tmp, "telegram", "old-1", "delivered", 1000)

        # Stub _loom_channel_send to (a) return delivery_id and (b) write the record
        new_id = "new-99"

        def fake_send(channel, recipient, text):
            _make_terminal_record(self.tmp, "telegram", new_id, "delivered", 5000)
            return {"ok": True, "payload": {"delivery_id": new_id}}

        with mock.patch.object(_mg, "_loom_channel_send", side_effect=fake_send):
            result = _mg._verify_channel_round_trip(
                "telegram", "5555", "hello", timeout_seconds=2.0, poll_interval_seconds=0.05,
            )
        self.assertEqual(result["status"], "delivered")
        self.assertEqual(result["delivery_id"], new_id)
        self.assertNotEqual(result["pre_head_chain_hash"], "")
        self.assertNotEqual(result["post_head_chain_hash"], "")
        self.assertNotEqual(result["pre_head_chain_hash"], result["post_head_chain_hash"])
        ext = result["extension_receipt"]
        self.assertEqual(ext["delivery_id"], new_id)
        self.assertEqual(ext["chain_hash"], result["post_head_chain_hash"])

    def test_failed_status_propagates(self):
        new_id = "bad-1"

        def fake_send(channel, recipient, text):
            _make_terminal_record(self.tmp, "telegram", new_id, "failed", 7000)
            return {"ok": True, "payload": {"delivery_id": new_id}}

        with mock.patch.object(_mg, "_loom_channel_send", side_effect=fake_send):
            result = _mg._verify_channel_round_trip(
                "telegram", "5555", "hi", timeout_seconds=2.0, poll_interval_seconds=0.05,
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["delivery_id"], new_id)

    def test_timeout_when_no_terminal_status_appears(self):
        new_id = "stuck-1"

        def fake_send(channel, recipient, text):
            # Write a queued (non-terminal) record only
            delivery_dir = self.tmp / "state" / "channels" / "delivery"
            rec = {
                "channel_id": "telegram",
                "delivery_id": new_id,
                "status": "queued",
                "recipient": "5555",
                "submitted_at_unix_ms": 9000,
            }
            (delivery_dir / f"9000-{new_id}.json").write_text(json.dumps(rec), encoding="utf-8")
            return {"ok": True, "payload": {"delivery_id": new_id}}

        with mock.patch.object(_mg, "_loom_channel_send", side_effect=fake_send):
            t0 = time.time()
            result = _mg._verify_channel_round_trip(
                "telegram", "5555", "hi", timeout_seconds=1.2, poll_interval_seconds=0.1,
            )
            elapsed = time.time() - t0
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["delivery_id"], new_id)
        self.assertGreaterEqual(elapsed, 1.0)
        self.assertLess(elapsed, 4.0)

    def test_schema_version_in_terminal_paths(self):
        for status in ("delivered", "failed"):
            new_id = f"schema-{status}"

            def fake_send(channel, recipient, text, _s=status, _id=new_id):
                _make_terminal_record(self.tmp, "telegram", _id, _s, 10000)
                return {"ok": True, "payload": {"delivery_id": _id}}

            with mock.patch.object(_mg, "_loom_channel_send", side_effect=fake_send):
                result = _mg._verify_channel_round_trip(
                    "telegram", "5555", "hi", timeout_seconds=1.0, poll_interval_seconds=0.05,
                )
            self.assertEqual(result["schema_version"], "meridian.channels.verify.v1")


class HealthTelegramPollingSurfaceTests(unittest.TestCase):
    def test_telegram_polling_state_surfaced(self):
        class FakeTg(_mg.ChannelAdapter):
            def __init__(self):
                super().__init__(runtime=None, name="telegram")
                self._active = True
                self.polling_state = "polling"
                self.polling_conflict_detail = ""
            def start(self): pass
            def stop(self): pass
            def send_message(self, text, *, source="runtime"): pass

        tg = FakeTg()
        result = _mg._build_multi_channel_health(adapters=[tg])
        ch = next(c for c in result["channels"] if c["channel_id"] == "telegram")
        self.assertEqual(ch["poll_state"]["state"], "polling")
        self.assertTrue(ch["poll_state"]["enabled"])

    def test_telegram_conflict_detail_surfaced(self):
        class FakeTg(_mg.ChannelAdapter):
            def __init__(self):
                super().__init__(runtime=None, name="telegram")
                self._active = True
                self.polling_state = "conflict"
                self.polling_conflict_detail = "another poller owns the token"
            def start(self): pass
            def stop(self): pass
            def send_message(self, text, *, source="runtime"): pass

        tg = FakeTg()
        result = _mg._build_multi_channel_health(adapters=[tg])
        ch = next(c for c in result["channels"] if c["channel_id"] == "telegram")
        self.assertEqual(ch["poll_state"]["state"], "conflict")
        self.assertIn("another poller", ch["poll_state"]["detail"])

    def test_external_poll_state_takes_precedence_over_polling_state(self):
        # ExternalWebhookAdapter has both poll_state (its own) and not polling_state.
        # Verify the logic prefers poll_state field when both are truly present.
        class HybridAdapter(_mg.ChannelAdapter):
            def __init__(self):
                super().__init__(runtime=None, name="zalo")
                self._active = True
                self.poll_state = "polling"
                self.poll_state_detail = "ok"
                self.poll_last_message_id = "msg-99"
                self.poll_enabled = True
                self.polling_state = "should_not_be_used"
            def start(self): pass
            def stop(self): pass
            def send_message(self, text, *, source="runtime"): pass

        h = HybridAdapter()
        result = _mg._build_multi_channel_health(adapters=[h])
        ch = next(c for c in result["channels"] if c["channel_id"] == "zalo")
        self.assertEqual(ch["poll_state"]["state"], "polling")
        self.assertEqual(ch["poll_state"]["last_message_id"], "msg-99")


if __name__ == "__main__":
    unittest.main()
