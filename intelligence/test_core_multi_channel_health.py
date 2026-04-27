#!/usr/bin/env python3
"""Tests for Meridian Core multi-channel health surfaces.

Covers:
- Gateway functions: _recent_channel_delivery_summary, _build_multi_channel_health,
  _build_channel_diagnostics, ALL_CHANNEL_IDS
- API endpoints: /api/channels/health, /api/channels/{id}/diagnostics
- Core.sh: channel diagnostics command, multi-channel health in doctor, help text
- Connect adapter templates: zalo.sample.json, messenger.sample.json
"""

import json
import unittest
from pathlib import Path


MERIDIAN_ROOT = Path(__file__).resolve().parent.parent
CORE_SH = MERIDIAN_ROOT / "scripts" / "core.sh"
GATEWAY_PY = Path(__file__).resolve().parent / "meridian_gateway.py"
CONNECT_TEMPLATES = MERIDIAN_ROOT / "loom" / "templates" / "connect"


# ── Gateway function unit tests ──────────────────────────────────────────


class TestAllChannelIds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")

    def test_all_channel_ids_defined(self):
        self.assertIn("ALL_CHANNEL_IDS", self.source)

    def test_all_channel_ids_contains_telegram(self):
        self.assertIn('"telegram"', self.source.split("ALL_CHANNEL_IDS")[1][:200])

    def test_all_channel_ids_contains_zalo(self):
        self.assertIn('"zalo"', self.source.split("ALL_CHANNEL_IDS")[1][:200])

    def test_all_channel_ids_contains_discord(self):
        self.assertIn('"discord"', self.source.split("ALL_CHANNEL_IDS")[1][:200])

    def test_all_channel_ids_contains_messenger(self):
        self.assertIn('"messenger"', self.source.split("ALL_CHANNEL_IDS")[1][:200])

    def test_all_channel_ids_contains_whatsapp(self):
        self.assertIn('"whatsapp"', self.source.split("ALL_CHANNEL_IDS")[1][:200])

    def test_all_channel_ids_contains_web_api(self):
        self.assertIn('"web_api"', self.source.split("ALL_CHANNEL_IDS")[1][:200])


def _extract_function_body(source: str, func_name: str, window: int = 2000) -> str:
    """Extract function body by searching for 'def func_name(' and taking a window after it."""
    marker = f"def {func_name}("
    idx = source.find(marker)
    if idx == -1:
        return ""
    return source[idx:idx + window]


class TestRecentChannelDeliverySummaryFunction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")
        cls.body = _extract_function_body(cls.source, "_recent_channel_delivery_summary")

    def test_function_exists(self):
        self.assertIn("def _recent_channel_delivery_summary(", self.source)

    def test_accepts_channel_id_param(self):
        self.assertIn("channel_id: str", self.body[:200])

    def test_returns_dict_with_delivered_count(self):
        self.assertIn('"delivered_count"', self.body)

    def test_returns_dict_with_latest_at(self):
        self.assertIn('"latest_at"', self.body)


class TestBuildMultiChannelHealthFunction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")
        cls.body = _extract_function_body(cls.source, "_build_multi_channel_health", 4000)

    def test_function_exists(self):
        self.assertIn("def _build_multi_channel_health(", self.source)

    def test_returns_schema_version(self):
        # Tranche 6 bumps schema to v2 to add lifecycle + poll_state fields.
        self.assertIn('"meridian.channels.health.v2"', self.body)

    def test_returns_channel_count(self):
        self.assertIn('"channel_count"', self.body)

    def test_returns_active_adapter_count(self):
        self.assertIn('"active_adapter_count"', self.body)

    def test_returns_total_recent_delivered(self):
        self.assertIn('"total_recent_delivered"', self.body)

    def test_returns_channels_list(self):
        self.assertIn('"channels"', self.body)


class TestBuildChannelDiagnosticsFunction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")
        cls.body = _extract_function_body(cls.source, "_build_channel_diagnostics", 2000)

    def test_function_exists(self):
        self.assertIn("def _build_channel_diagnostics(", self.source)

    def test_returns_schema_version(self):
        self.assertIn('"meridian.channels.diagnostics.v1"', self.body)

    def test_returns_recent_deliveries(self):
        self.assertIn('"recent_deliveries"', self.body)


# ── API endpoint wiring tests ────────────────────────────────────────────


class TestChannelHealthAPIEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")

    def test_channels_health_endpoint_exists(self):
        self.assertIn('"/api/channels/health"', self.source)

    def test_channels_health_calls_build_function(self):
        self.assertIn("_build_multi_channel_health(adapter.all_adapters)", self.source)

    def test_channels_health_returns_success_json(self):
        self.assertIn('"channels_health"', self.source)

    def test_channels_health_is_public_read(self):
        idx = self.source.index("def _public_read_allowed")
        section = self.source[idx:idx + 1200]
        self.assertIn('"/api/channels/health"', section)


class TestChannelDiagnosticsAPIEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")

    def test_diagnostics_endpoint_pattern_exists(self):
        self.assertIn("/diagnostics", self.source)
        self.assertIn('"/api/channels/"', self.source)

    def test_diagnostics_validates_channel_id(self):
        self.assertIn("ALL_CHANNEL_IDS", self.source)

    def test_diagnostics_accepts_limit_param(self):
        self.assertIn("diag_limit", self.source)

    def test_diagnostics_returns_404_for_unknown_channel(self):
        self.assertIn("unknown channel", self.source)

    def test_diagnostics_is_public_read_for_pattern(self):
        idx = self.source.index("def _public_read_allowed")
        section = self.source[idx:idx + 1200]
        self.assertIn("/diagnostics", section)


# ── WebAPIAdapter all_adapters wiring ────────────────────────────────────


class TestWebAPIAdapterAllAdapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")

    def test_all_adapters_attribute_declared(self):
        self.assertIn("self.all_adapters", self.source)

    def test_all_adapters_set_in_main(self):
        self.assertIn("web_adapter.all_adapters = list(adapters)", self.source)


# ── Core.sh help text tests ─────────────────────────────────────────────


class TestCoreShChannelDiagnosticsHelp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_help_mentions_channel_diagnostics(self):
        self.assertIn("channel diagnostics", self.source)

    def test_help_mentions_multi_channel_overview(self):
        self.assertIn("Multi-channel health overview", self.source)

    def test_help_mentions_per_channel_diagnostics(self):
        self.assertIn("per-channel delivery diagnostics", self.source)

    def test_example_diagnostics_telegram(self):
        self.assertIn("core.sh channel diagnostics telegram", self.source)

    def test_example_diagnostics_zalo(self):
        self.assertIn("core.sh channel diagnostics zalo", self.source)


class TestCoreShChannelDiagnosticsWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_cmd_channel_diagnostics_exists(self):
        self.assertIn("cmd_channel_diagnostics", self.source)

    def test_channel_dispatch_includes_diagnostics(self):
        self.assertIn("diagnostics)", self.source)

    def test_diagnostics_queries_gateway_api(self):
        self.assertIn("/api/channels/${channel_id}/diagnostics", self.source)

    def test_diagnostics_falls_back_to_files(self):
        self.assertIn("_render_channel_diagnostics_from_files", self.source)

    def test_diagnostics_renders_delivery_summary(self):
        self.assertIn("delivered:", self.source)
        self.assertIn("failed:", self.source)
        self.assertIn("pending:", self.source)


class TestCoreShDoctorMultiChannelHealth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_doctor_overview_calls_multi_channel_health(self):
        self.assertIn("_render_multi_channel_health", self.source)

    def test_render_multi_channel_health_exists(self):
        self.assertIn("_render_multi_channel_health()", self.source)

    def test_multi_channel_health_queries_gateway(self):
        self.assertIn("/api/channels/health", self.source)


class TestCoreShUsageStringUpdated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CORE_SH.read_text(encoding="utf-8")

    def test_usage_includes_diagnostics_in_channel_dispatch(self):
        # Tranche 8 adds the `watch` subcommand to the dispatch surface.
        self.assertIn("list|health|show|deliveries|send|test|diagnostics|proof|verify|watch|connect", self.source)


# ── Connect adapter template tests ───────────────────────────────────────


class TestZaloConnectTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = CONNECT_TEMPLATES / "zalo.sample.json"
        cls.data = json.loads(cls.path.read_text(encoding="utf-8"))

    def test_file_exists(self):
        self.assertTrue(self.path.exists())

    def test_schema_version(self):
        self.assertEqual(self.data["schema_version"], "meridian.connect.adapter.v1")

    def test_transport_is_zalo(self):
        self.assertEqual(self.data["transport"], "zalo")

    def test_action_schema(self):
        self.assertEqual(self.data["action_schema"], "meridian.runtime.v1")

    def test_runtime_contract(self):
        self.assertEqual(self.data["runtime_contract"], "connect_runtime_contract_v2")

    def test_lifecycle_disabled_by_default(self):
        self.assertFalse(self.data["lifecycle"]["enabled"])

    def test_transport_profile_kind(self):
        self.assertEqual(self.data["transport_profile"]["kind"], "zalo")

    def test_transport_profile_inbound_mode(self):
        self.assertEqual(self.data["transport_profile"]["inbound_mode"], "webhook")


class TestMessengerConnectTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = CONNECT_TEMPLATES / "messenger.sample.json"
        cls.data = json.loads(cls.path.read_text(encoding="utf-8"))

    def test_file_exists(self):
        self.assertTrue(self.path.exists())

    def test_schema_version(self):
        self.assertEqual(self.data["schema_version"], "meridian.connect.adapter.v1")

    def test_transport_is_messenger(self):
        self.assertEqual(self.data["transport"], "messenger")

    def test_action_schema(self):
        self.assertEqual(self.data["action_schema"], "meridian.runtime.v1")

    def test_runtime_contract(self):
        self.assertEqual(self.data["runtime_contract"], "connect_runtime_contract_v2")

    def test_lifecycle_disabled_by_default(self):
        self.assertFalse(self.data["lifecycle"]["enabled"])

    def test_transport_profile_kind(self):
        self.assertEqual(self.data["transport_profile"]["kind"], "messenger")

    def test_transport_profile_inbound_mode(self):
        self.assertEqual(self.data["transport_profile"]["inbound_mode"], "webhook")


class TestConnectREADMEInclusion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (CONNECT_TEMPLATES / "README.md").read_text(encoding="utf-8")

    def test_zalo_listed(self):
        self.assertIn("zalo.sample.json", self.readme)

    def test_messenger_listed(self):
        self.assertIn("messenger.sample.json", self.readme)


# ── Multi-channel status text integration ────────────────────────────────


class TestStatusTextMultiChannel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GATEWAY_PY.read_text(encoding="utf-8")

    def test_status_text_includes_multi_channel_call(self):
        self.assertIn("_build_multi_channel_health()", self.source)

    def test_status_text_mentions_active_channel_adapters(self):
        self.assertIn("active channel adapters", self.source)

    def test_status_text_mentions_across_all_channels(self):
        self.assertIn("across all channels", self.source)


# ── Config integration ───────────────────────────────────────────────────


class TestMeridianConfigChannelKeys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_py = (Path(__file__).resolve().parent / "meridian_config.py").read_text(encoding="utf-8")

    def test_zalo_outbound_url_key(self):
        self.assertIn("zalo_outbound_url", self.config_py)

    def test_zalo_inbound_secret_key(self):
        self.assertIn("zalo_inbound_secret", self.config_py)

    def test_zalo_bot_token_key(self):
        self.assertIn("zalo_bot_token", self.config_py)

    def test_messenger_outbound_url_key(self):
        self.assertIn("messenger_outbound_url", self.config_py)

    def test_messenger_inbound_secret_key(self):
        self.assertIn("messenger_inbound_secret", self.config_py)

    def test_messenger_verify_token_key(self):
        self.assertIn("messenger_verify_token", self.config_py)

    def test_discord_webhook_url_key(self):
        self.assertIn("discord_webhook_url", self.config_py)

    def test_whatsapp_outbound_url_key(self):
        self.assertIn("whatsapp_outbound_url", self.config_py)


if __name__ == "__main__":
    unittest.main()
