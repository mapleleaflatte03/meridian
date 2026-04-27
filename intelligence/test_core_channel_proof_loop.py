#!/usr/bin/env python3
"""Tests for Meridian Tranche 6: Zalo poll bridge wiring + delivery proof loop.

Covers:
- ChannelAdapter base lifecycle tracking (started_at, last_success/error, counts).
- ExternalWebhookAdapter Zalo poll bridge fields and start/stop wiring.
- _zalo_normalize_update / _zalo_extract_text helpers.
- _build_channel_delivery_proof: sha256 receipt chain shape, head hash, ordering.
- Multi-channel health v2 schema (lifecycle + poll_state fields).
- /api/channels/{id}/proof endpoint dispatch wiring.
- core.sh: channel proof command wiring, _render_channel_proof_from_files,
  proof entry in usage and dispatch.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
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

    # Lifecycle base class fields
    def test_channel_adapter_has_lifecycle_lock(self):
        self.assertIn("self._lifecycle_lock = threading.Lock()", self.source)

    def test_channel_adapter_has_started_at(self):
        self.assertIn("self._started_at_unix", self.source)

    def test_channel_adapter_has_last_success(self):
        self.assertIn("self._last_success_at_unix", self.source)

    def test_channel_adapter_has_last_error_detail(self):
        self.assertIn("self._last_error_detail", self.source)

    def test_channel_adapter_has_consecutive_failures(self):
        self.assertIn("self._consecutive_failures", self.source)

    def test_channel_adapter_has_lifecycle_snapshot(self):
        self.assertIn("def lifecycle_snapshot(self)", self.source)

    def test_lifecycle_snapshot_returns_uptime_seconds(self):
        self.assertIn('"uptime_seconds"', self.source)

    def test_lifecycle_snapshot_returns_consecutive_failures(self):
        self.assertIn('"consecutive_failures"', self.source)

    # Telegram lifecycle wiring
    def test_telegram_records_lifecycle_started(self):
        idx = self.source.find("def start(self) -> None:\n        if not self.bot_token:")
        self.assertGreater(idx, 0)
        snippet = self.source[idx:idx + 800]
        self.assertIn("_record_lifecycle_started()", snippet)

    def test_telegram_records_success_and_failure(self):
        self.assertIn("self._record_lifecycle_success()", self.source)
        self.assertIn("self._record_lifecycle_failure(", self.source)

    def test_telegram_records_inbound(self):
        self.assertIn("self._record_lifecycle_inbound()", self.source)

    # External adapter Zalo poll bridge wiring
    def test_external_adapter_has_bot_token(self):
        self.assertIn("self.bot_token = str(bot_token", self.source)

    def test_external_adapter_has_poll_enabled(self):
        self.assertIn("self.poll_enabled = bool(poll_enabled)", self.source)

    def test_external_adapter_has_poll_state(self):
        self.assertIn("self.poll_state", self.source)

    def test_external_adapter_has_zalo_poll_loop(self):
        self.assertIn("def _zalo_poll_loop(self)", self.source)

    def test_external_adapter_starts_poll_thread(self):
        self.assertIn("poll bridge started", self.source)

    def test_external_adapter_stop_signals_poll_event(self):
        idx = self.source.find("def stop(self) -> None:")
        self.assertGreater(idx, 0)
        # find within ExternalWebhookAdapter (after class declaration)
        cls_idx = self.source.find("class ExternalWebhookAdapter")
        self.assertGreater(cls_idx, 0)
        snippet = self.source[cls_idx:cls_idx + 4000]
        self.assertIn("self.poll_stop_event.set()", snippet)

    # Zalo helpers
    def test_zalo_normalize_update_helper_exists(self):
        self.assertIn("def _zalo_normalize_update(item:", self.source)

    def test_zalo_extract_text_helper_exists(self):
        self.assertIn("def _zalo_extract_text(value:", self.source)

    # Proof builder + endpoint
    def test_build_channel_delivery_proof_exists(self):
        self.assertIn("def _build_channel_delivery_proof(channel_id:", self.source)

    def test_proof_builder_uses_sha256_receipt_chain(self):
        idx = self.source.find("def _build_channel_delivery_proof(")
        self.assertGreater(idx, 0)
        snippet = self.source[idx:idx + 3500]
        self.assertIn("hashlib.sha256", snippet)
        self.assertIn('"receipt_hash"', snippet)
        self.assertIn('"chain_hash"', snippet)
        self.assertIn('"head_chain_hash"', snippet)

    def test_proof_endpoint_registered(self):
        self.assertIn('request_path.endswith("/proof")', self.source)

    def test_proof_endpoint_in_public_read_allowed(self):
        idx = self.source.find("def _public_read_allowed(self, request_path: str)")
        self.assertGreater(idx, 0)
        snippet = self.source[idx:idx + 2000]
        self.assertIn('endswith("/proof")', snippet)

    def test_multi_channel_health_includes_lifecycle(self):
        idx = self.source.find("def _build_multi_channel_health(")
        self.assertGreater(idx, 0)
        snippet = self.source[idx:idx + 3000]
        self.assertIn('"lifecycle"', snippet)
        self.assertIn('"poll_state"', snippet)
        self.assertIn('"meridian.channels.health.v2"', snippet)

    def test_zalo_adapter_constructed_with_bot_token_and_poll_flag(self):
        self.assertIn("bot_token=str(config.get(\"zalo_bot_token\")", self.source)
        self.assertIn("poll_enabled=bool(config.get(\"zalo_poll_enabled\")", self.source)


class CoreShellSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_proof_subcommand_dispatched(self):
        self.assertIn("proof)\n            cmd_channel_proof", self.source)

    def test_proof_function_defined(self):
        self.assertIn("cmd_channel_proof()", self.source)

    def test_proof_file_renderer_defined(self):
        self.assertIn("_render_channel_proof_from_files()", self.source)

    def test_proof_documented_in_usage(self):
        self.assertIn("channel proof CH [N]", self.source)

    def test_proof_in_channel_command_usage_string(self):
        self.assertIn("|proof|", self.source)


# ── Importable function tests (with stubbed deps) ──────────────────────────


if str(INTEL) not in sys.path:
    sys.path.insert(0, str(INTEL))

# Reuse the heavy stubs and fully loaded module from test_gateway_brain_router.
# That module does all the dependency stubbing for us.
import test_gateway_brain_router as _tgbr  # noqa: E402
_mg = _tgbr.meridian_gateway


class ZaloHelperTests(unittest.TestCase):
    def test_extract_text_string(self):
        self.assertEqual(_mg._zalo_extract_text("hello"), "hello")

    def test_extract_text_dict(self):
        self.assertEqual(_mg._zalo_extract_text({"text": "hi"}), "hi")

    def test_extract_text_nested(self):
        self.assertEqual(_mg._zalo_extract_text({"message": {"content": "deep"}}), "deep")

    def test_extract_text_empty(self):
        self.assertEqual(_mg._zalo_extract_text({}), "")

    def test_normalize_returns_none_without_sender(self):
        self.assertIsNone(_mg._zalo_normalize_update({"text": "hi"}))

    def test_normalize_returns_none_without_text(self):
        self.assertIsNone(_mg._zalo_normalize_update({"fromuid": "u1"}))

    def test_normalize_minimal(self):
        out = _mg._zalo_normalize_update({"fromuid": "u1", "text": "hi", "message_id": "m1"})
        self.assertEqual(out["sender_id"], "u1")
        self.assertEqual(out["text"], "hi")
        self.assertEqual(out["message_id"], "m1")

    def test_normalize_uses_chat_id(self):
        out = _mg._zalo_normalize_update({"chat_id": "c9", "text": "ok"})
        self.assertEqual(out["sender_id"], "c9")

    def test_normalize_synthesizes_message_id(self):
        out = _mg._zalo_normalize_update({"fromuid": "u", "text": "t"})
        self.assertTrue(out["message_id"].startswith("zalo-"))


class DeliveryProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="meridian-proof-test-"))
        self.delivery_dir = self.tmp / "state" / "channels" / "delivery"
        self.delivery_dir.mkdir(parents=True)
        self._orig_root = _mg.LOOM_ROOT
        _mg.LOOM_ROOT = str(self.tmp)

    def tearDown(self):
        _mg.LOOM_ROOT = self._orig_root
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_record(self, channel_id: str, did: str, status: str, submitted_ms: int):
        rec = {
            "channel_id": channel_id,
            "delivery_id": did,
            "status": status,
            "recipient": "r1",
            "submitted_at_unix_ms": submitted_ms,
            "completed_at_unix_ms": submitted_ms + 100,
            "external_ref": f"ext-{did}",
        }
        (self.delivery_dir / f"{submitted_ms}-{did}.json").write_text(
            json.dumps(rec), encoding="utf-8"
        )
        return rec

    def test_empty_channel_returns_empty_chain(self):
        proof = _mg._build_channel_delivery_proof("telegram", limit=10)
        self.assertEqual(proof["channel_id"], "telegram")
        self.assertEqual(proof["receipt_count"], 0)
        self.assertEqual(proof["receipts"], [])
        self.assertEqual(proof["head_chain_hash"], "")

    def test_chain_links_each_receipt_to_previous(self):
        self._write_record("telegram", "d1", "delivered", 1000)
        self._write_record("telegram", "d2", "delivered", 2000)
        self._write_record("telegram", "d3", "failed", 3000)
        proof = _mg._build_channel_delivery_proof("telegram", limit=10)
        self.assertEqual(proof["receipt_count"], 3)
        receipts = proof["receipts"]
        # First in chain has empty prev
        self.assertEqual(receipts[0]["prev_chain_hash"], "")
        # Each prev_chain_hash matches previous chain_hash
        self.assertEqual(receipts[1]["prev_chain_hash"], receipts[0]["chain_hash"])
        self.assertEqual(receipts[2]["prev_chain_hash"], receipts[1]["chain_hash"])
        # Head hash matches last
        self.assertEqual(proof["head_chain_hash"], receipts[-1]["chain_hash"])
        # Records appear in chronological order (oldest first)
        self.assertEqual(receipts[0]["delivery_id"], "d1")
        self.assertEqual(receipts[2]["delivery_id"], "d3")

    def test_chain_hash_is_deterministic_sha256(self):
        rec = self._write_record("zalo", "z1", "delivered", 5000)
        proof = _mg._build_channel_delivery_proof("zalo", limit=10)
        canonical = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        expected_receipt = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        expected_chain = hashlib.sha256(f":{expected_receipt}".encode("utf-8")).hexdigest()
        self.assertEqual(proof["receipts"][0]["receipt_hash"], expected_receipt)
        self.assertEqual(proof["receipts"][0]["chain_hash"], expected_chain)
        self.assertEqual(proof["head_chain_hash"], expected_chain)

    def test_filters_by_channel(self):
        self._write_record("telegram", "tg1", "delivered", 100)
        self._write_record("zalo", "z1", "delivered", 200)
        self._write_record("zalo", "z2", "delivered", 300)
        tg = _mg._build_channel_delivery_proof("telegram", limit=10)
        zl = _mg._build_channel_delivery_proof("zalo", limit=10)
        self.assertEqual(tg["receipt_count"], 1)
        self.assertEqual(zl["receipt_count"], 2)

    def test_limit_respected(self):
        for i in range(5):
            self._write_record("telegram", f"d{i}", "delivered", 1000 + i)
        proof = _mg._build_channel_delivery_proof("telegram", limit=2)
        self.assertEqual(proof["receipt_count"], 2)
        self.assertEqual(proof["total_records"], 5)
        # Should be the most recent 2 in chronological order (d3, d4)
        ids = [r["delivery_id"] for r in proof["receipts"]]
        self.assertEqual(ids, ["d3", "d4"])

    def test_schema_version_set(self):
        self._write_record("telegram", "x1", "delivered", 1)
        proof = _mg._build_channel_delivery_proof("telegram", limit=1)
        self.assertEqual(proof["schema_version"], "meridian.channels.proof.v1")


class LifecycleSnapshotTests(unittest.TestCase):
    def _make(self):
        # Minimal ChannelAdapter subclass
        class A(_mg.ChannelAdapter):
            def start(self): pass
            def stop(self): pass
            def send_message(self, text, *, source="runtime"): pass
        return A(runtime=None, name="t")

    def test_initial_snapshot_zero(self):
        a = self._make()
        snap = a.lifecycle_snapshot()
        self.assertEqual(snap["name"], "t")
        self.assertFalse(snap["active"])
        self.assertEqual(snap["uptime_seconds"], 0.0)
        self.assertEqual(snap["consecutive_failures"], 0)
        self.assertEqual(snap["success_count"], 0)
        self.assertEqual(snap["failure_count"], 0)

    def test_started_increments_started_at(self):
        a = self._make()
        a._record_lifecycle_started()
        snap = a.lifecycle_snapshot()
        self.assertGreater(snap["started_at_unix"], 0.0)
        self.assertGreaterEqual(snap["uptime_seconds"], 0.0)

    def test_success_resets_consecutive_failures(self):
        a = self._make()
        a._record_lifecycle_failure("boom")
        a._record_lifecycle_failure("boom2")
        self.assertEqual(a.lifecycle_snapshot()["consecutive_failures"], 2)
        a._record_lifecycle_success()
        snap = a.lifecycle_snapshot()
        self.assertEqual(snap["consecutive_failures"], 0)
        self.assertEqual(snap["success_count"], 1)
        self.assertEqual(snap["failure_count"], 2)

    def test_last_error_detail_truncated(self):
        a = self._make()
        a._record_lifecycle_failure("x" * 1000)
        snap = a.lifecycle_snapshot()
        self.assertEqual(len(snap["last_error_detail"]), 500)

    def test_inbound_records_timestamp(self):
        a = self._make()
        self.assertEqual(a.lifecycle_snapshot()["last_inbound_at_unix"], 0.0)
        a._record_lifecycle_inbound()
        self.assertGreater(a.lifecycle_snapshot()["last_inbound_at_unix"], 0.0)


class ExternalWebhookAdapterPollWiringTests(unittest.TestCase):
    def test_zalo_adapter_with_no_creds_does_not_activate(self):
        adapter = _mg.ExternalWebhookAdapter(
            runtime=None, name="zalo",
            outbound_url="", inbound_secret="", bot_token="", poll_enabled=False,
        )
        adapter.start()
        self.assertFalse(adapter._active)

    def test_zalo_adapter_with_inbound_secret_only_activates(self):
        adapter = _mg.ExternalWebhookAdapter(
            runtime=None, name="zalo",
            inbound_secret="s", poll_enabled=False,
        )
        adapter.start()
        self.assertTrue(adapter._active)
        # No poll thread since poll_enabled=False
        self.assertIsNone(adapter.poll_thread)

    def test_zalo_adapter_poll_disabled_when_no_bot_token(self):
        adapter = _mg.ExternalWebhookAdapter(
            runtime=None, name="zalo",
            outbound_url="https://example.invalid/send",
            poll_enabled=True, bot_token="",
        )
        adapter.start()
        # Activated via outbound_url, but poll thread not started without bot token
        self.assertTrue(adapter._active)
        self.assertIsNone(adapter.poll_thread)

    def test_poll_loop_handles_no_token_gracefully(self):
        adapter = _mg.ExternalWebhookAdapter(
            runtime=None, name="zalo", bot_token="", poll_enabled=True,
        )
        adapter._zalo_poll_loop()
        self.assertEqual(adapter.poll_state, "disabled")


class MultiChannelHealthV2Tests(unittest.TestCase):
    def test_health_returns_v2_schema(self):
        result = _mg._build_multi_channel_health(adapters=[])
        self.assertEqual(result["schema_version"], "meridian.channels.health.v2")
        self.assertIn("channels", result)
        self.assertEqual(len(result["channels"]), len(_mg.ALL_CHANNEL_IDS))

    def test_health_includes_lifecycle_field_per_channel(self):
        result = _mg._build_multi_channel_health(adapters=[])
        for ch in result["channels"]:
            self.assertIn("lifecycle", ch)
            self.assertIn("poll_state", ch)

    def test_health_picks_up_lifecycle_from_active_adapter(self):
        class A(_mg.ChannelAdapter):
            def start(self): pass
            def stop(self): pass
            def send_message(self, text, *, source="runtime"): pass
        a = A(runtime=None, name="telegram")
        a._active = True
        a._record_lifecycle_started()
        a._record_lifecycle_success()
        result = _mg._build_multi_channel_health(adapters=[a])
        tg = next(c for c in result["channels"] if c["channel_id"] == "telegram")
        self.assertTrue(tg["adapter_active"])
        self.assertEqual(tg["lifecycle"]["success_count"], 1)


if __name__ == "__main__":
    unittest.main()
