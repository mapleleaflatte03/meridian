#!/usr/bin/env python3
import importlib.util
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock


def _resolve_workspace() -> Path:
    env_workspace = os.getenv("MERIDIAN_WORKSPACE_PATH")
    if env_workspace:
        return Path(env_workspace)
    return Path(__file__).resolve().parent


WORKSPACE = _resolve_workspace()
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))


def _install_mcp_server_stub() -> None:
    if "company.mcp_server" not in sys.modules:
        stub = types.ModuleType("company.mcp_server")

        def _unsupported(*_args, **_kwargs):
            raise RuntimeError("company.mcp_server stub invoked unexpectedly")

        stub.do_on_demand_research_route = _unsupported
        stub.do_qa_verify_route = _unsupported
        stub._specialist_direct_provider_fallback = _unsupported
        stub._shared_run_loom_capability = _unsupported
        stub._loom_runtime_context = _unsupported
        sys.modules["company.mcp_server"] = stub

    if "accounting" not in sys.modules:
        accounting = types.ModuleType("accounting")
        accounting.append_tx = lambda *_args, **_kwargs: None
        accounting.load_ledger = lambda *_args, **_kwargs: {"treasury": {"cash_usd": 0.0}}
        accounting.save_ledger = lambda *_args, **_kwargs: None
        sys.modules["accounting"] = accounting

    if "audit" not in sys.modules:
        audit = types.ModuleType("audit")
        audit.log_event = lambda *_args, **_kwargs: None
        sys.modules["audit"] = audit

    if "capsule" not in sys.modules:
        capsule = types.ModuleType("capsule")
        base = Path(tempfile.gettempdir()) / "meridian-intelligence-tests"
        base.mkdir(parents=True, exist_ok=True)
        ledger_path = base / "ledger.json"
        if not ledger_path.exists():
            ledger_path.write_text('{"treasury":{"cash_usd":0.0}}\n', encoding="utf-8")
        capsule.ensure_treasury_aliases = lambda *_args, **_kwargs: {"ledger": str(ledger_path)}
        capsule.ledger_path = lambda *_args, **_kwargs: str(ledger_path)
        sys.modules["capsule"] = capsule

    if "court" not in sys.modules:
        court = types.ModuleType("court")
        court.file_violation = lambda *_args, **_kwargs: {}
        court.get_restrictions = lambda *_args, **_kwargs: {}
        sys.modules["court"] = court

    if "warrants" not in sys.modules:
        warrants = types.ModuleType("warrants")
        warrants.issue_warrant = lambda *_args, **_kwargs: {}
        warrants.mark_warrant_executed = lambda *_args, **_kwargs: {}
        warrants.review_warrant = lambda *_args, **_kwargs: {}
        warrants.validate_warrant_for_execution = lambda *_args, **_kwargs: {"valid": True}
        sys.modules["warrants"] = warrants

    if "loom_runtime_client" not in sys.modules:
        runtime_client = types.ModuleType("loom_runtime_client")
        runtime_client.estimate_capability_cost_usd = lambda *_args, **_kwargs: 0.0
        runtime_client.format_estimated_cost_usd = lambda *_args, **_kwargs: "$0.00"
        sys.modules["loom_runtime_client"] = runtime_client

    if "loom_runtime_discovery" not in sys.modules:
        runtime_discovery = types.ModuleType("loom_runtime_discovery")
        runtime_discovery.preferred_loom_bin = lambda *_args, **_kwargs: "/usr/bin/loom"
        runtime_discovery.preferred_loom_root = lambda *_args, **_kwargs: str(
            Path(tempfile.gettempdir()) / "meridian-intelligence-tests"
        )
        runtime_discovery.runtime_value = (
            lambda _key, default=None, *_args, **_kwargs: default
        )
        sys.modules["loom_runtime_discovery"] = runtime_discovery

    if "session_history" not in sys.modules:
        session_history = types.ModuleType("session_history")
        session_history.append_session_event = lambda *_args, **_kwargs: None
        session_history.load_session_events = lambda *_args, **_kwargs: []
        sys.modules["session_history"] = session_history

    if "subscription_service" not in sys.modules:
        subscription_service = types.ModuleType("subscription_service")
        subscription_service.public_checkout_offer = lambda *_args, **_kwargs: {}
        subscription_service.subscription_summary = lambda *_args, **_kwargs: {}
        sys.modules["subscription_service"] = subscription_service

    if "team_topology" not in sys.modules:
        team_topology = types.ModuleType("team_topology")
        team_topology.SPECIALIST_KEYS = ("ATLAS", "SENTINEL", "FORGE", "QUILL", "AEGIS", "PULSE")

        class _Agent:
            def __init__(self, env_key, registry_id, handle, name, profile_name, model, task_kind):
                self.env_key = env_key
                self.registry_id = registry_id
                self.handle = handle
                self.name = name
                self.profile_name = profile_name
                self.model = model
                self.task_kind = task_kind

        class _Topology:
            def __init__(self):
                self.org_id = "org_test"
                self.manager = _Agent(
                    "MANAGER",
                    "agent_manager",
                    "main",
                    "Leviathann",
                    "manager_primary",
                    "reasoner-small",
                    "manage",
                )
                self.specialists = (
                    _Agent("ATLAS", "agent_atlas", "atlas", "Atlas", "atlas_specialist", "reasoner-small", "research"),
                    _Agent("SENTINEL", "agent_sentinel", "sentinel", "Sentinel", "sentinel_specialist", "reasoner-small", "verify"),
                    _Agent("FORGE", "agent_forge", "forge", "Forge", "forge_specialist", "reasoner-small", "execute"),
                    _Agent("QUILL", "agent_quill", "quill", "Quill", "quill_specialist", "reasoner-small", "write"),
                    _Agent("AEGIS", "agent_aegis", "aegis", "Aegis", "aegis_specialist", "reasoner-small", "qa_gate"),
                    _Agent("PULSE", "agent_pulse", "pulse", "Pulse", "pulse_specialist", "reasoner-small", "compress"),
                )

            def specialist_by_id(self, agent_id):
                token = str(agent_id or "").strip().lower()
                for agent in self.specialists:
                    if token in {agent.registry_id.lower(), agent.handle.lower(), agent.name.lower()}:
                        return agent
                return None

        team_topology.load_team_topology = lambda *_args, **_kwargs: _Topology()
        team_topology.sync_loom_team_profiles = lambda *_args, **_kwargs: {"ok": True}
        team_topology.default_imported_history_dir = (
            lambda *_args, **_kwargs: Path(tempfile.gettempdir()) / "meridian-intelligence-tests" / "imported"
        )
        sys.modules["team_topology"] = team_topology


_install_mcp_server_stub()

spec = importlib.util.spec_from_file_location("meridian_gateway_test_brain_router", WORKSPACE / "meridian_gateway.py")
meridian_gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meridian_gateway)


class GatewayBrainRouterIntegrationTests(unittest.TestCase):
    def test_run_codex_exec_delegates_to_brain_router(self):
        expected = {
            "ok": True,
            "output_text": "router answer",
            "provider_profile": "manager_primary",
            "transport_kind": "http_json",
            "auth_mode": "bearer_pool",
            "model": "reasoner-small",
        }
        with mock.patch.object(
            meridian_gateway.brain_router,
            "execute_manager",
            return_value=expected,
        ) as exec_mock:
            result = meridian_gateway._run_codex_exec(
                system_prompt="sys",
                user_prompt="usr",
                model="reasoner-small",
                timeout=5,
            )
        self.assertEqual(result, expected)
        exec_mock.assert_called_once()

    def test_manager_exec_metadata_delegates_to_brain_router(self):
        expected = {
            "provider_profile": "manager_primary",
            "model": "reasoner-small",
            "transport_kind": "http_json",
            "auth_mode": "bearer_pool",
        }
        with mock.patch.object(
            meridian_gateway.brain_router,
            "manager_exec_metadata",
            return_value=expected,
        ) as meta_mock:
            result = meridian_gateway._manager_exec_metadata("reasoner-small")
        self.assertEqual(result, expected)
        meta_mock.assert_called_once()

    def test_loom_manager_defaults_prefers_brain_router_model(self):
        with mock.patch.object(
            meridian_gateway.brain_router,
            "manager_exec_metadata",
            return_value={
                "provider_profile": "manager_primary",
                "model": "reasoner-small",
                "transport_kind": "http_json",
                "auth_mode": "bearer_pool",
            },
        ):
            defaults = meridian_gateway._loom_manager_defaults()
        self.assertEqual(defaults["provider_profile"], "manager_primary")
        self.assertEqual(defaults["model"], "reasoner-small")

    def test_build_workflow_showcase_snapshot_returns_live_growth_shape(self):
        responses = {
            "/api/status": {
                "ok": True,
                "payload": {
                    "runtime_id": "loom_runtime_test",
                    "treasury": {"balance_usd": 123.45, "reserve_floor_usd": 50.0},
                    "authority": {"pending_approvals": [{"id": "a1"}]},
                    "cases": {"open": 2},
                    "alert_queue": {"queue_count": 4},
                },
            },
            "/api/runtime-proof": {
                "ok": True,
                "payload": {"proof_type": "receipt_merkle_root", "runtime_id": "loom_runtime_test"},
            },
            "/api/payouts": {
                "ok": True,
                "payload": {
                    "proposals": [{"id": "p1"}, {"id": "p2"}],
                    "execution_gate": {"phase_ok": False, "reason": "phase_gate_pending"},
                    "phase_machine": {"number": 2, "name": "manual_review"},
                },
            },
            "/api/treasury": {
                "ok": True,
                "payload": {"balance_usd": 123.45, "reserve_floor_usd": 50.0, "paid_orders": 7},
            },
        }

        def fake_workspace_get(path: str):
            return responses.get(path, {"ok": False, "payload": {}})

        with mock.patch.object(
            meridian_gateway,
            "_workspace_api_get_json",
            side_effect=fake_workspace_get,
        ), mock.patch.object(
            meridian_gateway,
            "_recent_telegram_delivery_summary",
            return_value={
                "checked_count": 3,
                "delivered_count": 2,
                "failed_count": 1,
                "pending_count": 0,
                "latest_status": "delivered",
                "latest_delivery_id": "delivery-1",
            },
        ):
            payload = meridian_gateway._build_workflow_showcase_snapshot()

        self.assertEqual(payload["schema_version"], "meridian.workflow_showcase.v1")
        self.assertEqual(payload["runtime_id"], "loom_runtime_test")
        self.assertEqual(payload["proof_type"], "receipt_merkle_root")
        self.assertEqual(payload["paid_orders"], 7)
        self.assertEqual(payload["payout_proposals"], 2)
        self.assertEqual(len(payload["workflows"]), 3)
        self.assertIn("telegram_delivery", payload)

    def test_web_adapter_public_read_routes_include_live_workflow_and_usdc_surfaces(self):
        adapter = meridian_gateway.WebAPIAdapter(mock.Mock(), "https://app.welliam.codes")
        handler_cls = adapter._make_handler()
        handler = handler_cls.__new__(handler_cls)

        self.assertTrue(handler._public_read_allowed("/api/workflows/showcase"))
        self.assertTrue(handler._public_read_allowed("/api/treasury"))
        self.assertTrue(handler._public_read_allowed("/api/payouts"))
        self.assertTrue(handler._public_read_allowed("/api/kernel-proof-bundle"))
        self.assertTrue(handler._public_read_allowed("/api/institution/template"))
        self.assertFalse(handler._public_read_allowed("/api/institution/license/catalog"))
        self.assertFalse(handler._public_read_allowed("/api/treasury/accounts"))
        self.assertFalse(handler._public_read_allowed("/api/unknown"))

    def test_gateway_returns_410_for_deprecated_institution_license_routes(self):
        gateway_source = (WORKSPACE / "meridian_gateway.py").read_text(encoding="utf-8")
        self.assertIn(
            '"open_source_mode"',
            gateway_source,
            "gateway must return open_source_mode deprecation for institution license routes",
        )


class GatewayLiveSurfaceAssetTests(unittest.TestCase):
    def test_meridian_js_exposes_shared_fetch_timeout_helper_for_all_live_surface_modules(self):
        asset_path = WORKSPACE / "company" / "www" / "assets" / "meridian.js"
        content = asset_path.read_text(encoding="utf-8")

        self.assertIn(
            "window.__meridianFetchJsonWithTimeout",
            content,
            "live surfaces must share one fetch helper across modules to avoid scope regressions",
        )
        self.assertGreaterEqual(
            content.count("var fetchJsonWithTimeout = window.__meridianFetchJsonWithTimeout;"),
            2,
            "both live snapshot and proof summary modules must bind the shared helper",
        )


class GatewayStatusCacheConsistencyTests(unittest.TestCase):
    def setUp(self):
        self._cache_snapshot = dict(meridian_gateway.WORKSPACE_STATUS_CACHE)
        self._refresh_in_flight = meridian_gateway.WORKSPACE_STATUS_REFRESH_IN_FLIGHT

    def tearDown(self):
        meridian_gateway.WORKSPACE_STATUS_CACHE.clear()
        meridian_gateway.WORKSPACE_STATUS_CACHE.update(self._cache_snapshot)
        meridian_gateway.WORKSPACE_STATUS_REFRESH_IN_FLIGHT = self._refresh_in_flight

    def test_workspace_status_snapshot_hydrates_missing_treasury_from_treasury_route(self):
        meridian_gateway.WORKSPACE_STATUS_CACHE["fetched_at_unix_ms"] = 0
        meridian_gateway.WORKSPACE_STATUS_CACHE["snapshot"] = None
        meridian_gateway.WORKSPACE_STATUS_REFRESH_IN_FLIGHT = False

        def fake_workspace_get(path: str, timeout_seconds: float):  # noqa: ARG001
            if path == "/api/status":
                return {
                    "ok": True,
                    "status_code": 200,
                    "payload": {
                        "runtime_id": "loom_native",
                        "slo": {"status": "healthy", "alert_count": 0},
                        "treasury": {"balance_usd": None, "reserve_floor_usd": None},
                    },
                }
            if path == "/api/treasury":
                return {
                    "ok": True,
                    "status_code": 200,
                    "payload": {"balance_usd": 52.47, "reserve_floor_usd": 50.5, "paid_orders": 1},
                }
            return {"ok": False, "status_code": 500, "payload": {"status": "error"}}

        with mock.patch.object(
            meridian_gateway,
            "_workspace_api_get_json_with_timeout",
            side_effect=fake_workspace_get,
        ):
            result = meridian_gateway._workspace_status_snapshot_cached()

        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["payload"]["treasury"]["balance_usd"], 52.47)
        self.assertEqual(result["payload"]["treasury"]["reserve_floor_usd"], 50.5)

    def test_workspace_status_snapshot_repairs_cached_treasury_nulls(self):
        meridian_gateway.WORKSPACE_STATUS_CACHE["fetched_at_unix_ms"] = int(time.time() * 1000)
        meridian_gateway.WORKSPACE_STATUS_CACHE["snapshot"] = {
            "runtime_id": "loom_native",
            "slo": {"status": "healthy", "alert_count": 0},
            "treasury": {"balance_usd": None, "reserve_floor_usd": None},
        }
        meridian_gateway.WORKSPACE_STATUS_REFRESH_IN_FLIGHT = False

        def fake_workspace_get(path: str, timeout_seconds: float):  # noqa: ARG001
            if path == "/api/treasury":
                return {
                    "ok": True,
                    "status_code": 200,
                    "payload": {"balance_usd": 52.47, "reserve_floor_usd": 50.5},
                }
            return {"ok": False, "status_code": 500, "payload": {"status": "error"}}

        with mock.patch.object(
            meridian_gateway,
            "_workspace_api_get_json_with_timeout",
            side_effect=fake_workspace_get,
        ):
            result = meridian_gateway._workspace_status_snapshot_cached()

        self.assertEqual(result["payload"]["gateway_cache"]["state"], "fresh")
        self.assertEqual(result["payload"]["treasury"]["balance_usd"], 52.47)
        self.assertEqual(result["payload"]["treasury"]["reserve_floor_usd"], 50.5)


if __name__ == "__main__":
    unittest.main()
