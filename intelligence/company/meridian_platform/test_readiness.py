#!/usr/bin/env python3
import importlib.util
import json
import io
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

_real_spec_from_file_location = importlib.util.spec_from_file_location


class _StubLoader:
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.internal_test_ids = lambda data=None, org_id=None: set()


def _spec_from_file_location(name, location, *args, **kwargs):
    if str(location).endswith(os.path.join('company', 'subscriptions.py')):
        return importlib.machinery.ModuleSpec(name, _StubLoader())
    return _real_spec_from_file_location(name, location, *args, **kwargs)


importlib.util.spec_from_file_location = _spec_from_file_location

_fake_treasury = types.ModuleType('treasury')
_fake_treasury.treasury_snapshot = lambda org_id=None: {
    'balance_usd': 0.0,
    'reserve_floor_usd': 0.0,
    'runway_usd': 0.0,
    'shortfall_usd': 0.0,
    'above_reserve': True,
} 
_fake_treasury.check_budget = lambda *args, **kwargs: (True, 'ok')
sys.modules.setdefault('treasury', _fake_treasury)

_fake_organizations = types.ModuleType('organizations')
_fake_organizations.load_orgs = lambda: {
    'organizations': {
        'org_founding': {
            'id': 'org_founding',
            'slug': 'meridian',
            'name': 'Meridian',
        }
    }
}
_fake_organizations.get_org = lambda org_id: _fake_organizations.load_orgs()['organizations'].get(org_id)
sys.modules.setdefault('organizations', _fake_organizations)

_fake_brief_quality = types.ModuleType('brief_quality')
_fake_brief_quality.analyze_brief = lambda path: {'passed': True}
sys.modules.setdefault('brief_quality', _fake_brief_quality)

_fake_treasury = types.ModuleType('treasury')
_fake_treasury.treasury_snapshot = lambda org_id=None: {
    'balance_usd': 0.0,
    'reserve_floor_usd': 0.0,
    'runway_usd': 0.0,
    'shortfall_usd': 0.0,
    'above_reserve': True,
}
_fake_treasury.check_budget = lambda *args, **kwargs: (True, 'ok')
sys.modules.setdefault('treasury', _fake_treasury)

_fake_authority = types.ModuleType('authority')
_fake_authority.check_authority = lambda *args, **kwargs: True
_fake_authority.is_kill_switch_engaged = lambda *args, **kwargs: False
sys.modules.setdefault('authority', _fake_authority)

READINESS_PATH = os.path.join(THIS_DIR, "readiness.py")
SPEC = importlib.util.spec_from_file_location("meridian_readiness", READINESS_PATH)
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)


class ReadinessVerdictTests(unittest.TestCase):
    def _fake_run(self, runtime_ok=True, preflight_ok=True):
        def fake_run(cmd, cwd=readiness.WORKSPACE, timeout=30):
            if len(cmd) >= 2 and cmd[1] == "health":
                return {
                    "ok": runtime_ok,
                    "returncode": 0 if runtime_ok else 1,
                    "stdout": json.dumps({"status": "healthy"}) if runtime_ok else json.dumps({"status": "degraded"}),
                    "stderr": "",
                }
            if len(cmd) >= 3 and cmd[1:3] == ["service", "status"]:
                return {
                    "ok": runtime_ok,
                    "returncode": 0 if runtime_ok else 1,
                    "stdout": json.dumps({"running": runtime_ok, "service_status": "running" if runtime_ok else "stopped", "health": "healthy" if runtime_ok else "degraded", "transport": "socket+http"}),
                    "stderr": "",
                }
            if len(cmd) >= 2 and cmd[1] == readiness.CI_VERTICAL_PY:
                return {
                    "ok": preflight_ok,
                    "returncode": 0 if preflight_ok else 1,
                    "stdout": "PREFLIGHT: OK" if preflight_ok else "PREFLIGHT: BLOCKED -- policy gate",
                    "stderr": "",
                }
            raise AssertionError(f"Unexpected command: {cmd}")

        return fake_run

    def _collect(self, treasury, phase_num, phase_name, preflight_ok):
        with patch.object(readiness, "_run", side_effect=self._fake_run(preflight_ok=preflight_ok)), \
             patch.object(readiness, "_runtime_env_defaults", return_value={'MERIDIAN_INTELLIGENCE_EXEC_RUNTIME': 'legacy'}), \
             patch.object(readiness, "treasury_snapshot", return_value=treasury), \
             patch.object(readiness.status_surface, "persistence_snapshot", return_value={
                 'backend': 'file-backed-json-jsonl',
                 'db': {'status': 'absent'},
                 'seams': [],
             }), \
             patch.object(readiness.status_surface, "observability_snapshot", return_value={
                 'backend': 'file-backed-jsonl',
                 'metrics': {
                     'audit': {'total_events': 0},
                     'metering': {'total_cost_usd': 0.0},
                 },
                 'slo': {'status': 'not_formalized'},
             }), \
             patch.object(readiness._phase_mod, "evaluate", return_value=(phase_num, {
                 "name": phase_name,
                 "next_phase": phase_num + 1 if phase_num < 6 else None,
                 "next_phase_name": "Next Phase" if phase_num < 6 else None,
                 "next_unlock": "Do the next thing" if phase_num < 6 else None,
             })), \
             patch.object(readiness, "_latest_brief", return_value={"exists": False, "path": None, "date": None}), \
             patch.object(readiness, "_delivery_targets", return_value={
                 "ok": True,
                 "count": 0,
                 "internal_test_count": 2,
                 "targets": ["1053016694", "6114408283"],
                 "external_targets": [],
                 "stderr": "",
             }):
            return readiness.collect()

    def test_owner_blocked_treasury_takes_precedence_over_phase(self):
        report = self._collect(
            treasury={
                "balance_usd": 2.0,
                "reserve_floor_usd": 50.0,
                "runway_usd": -48.0,
                "shortfall_usd": 48.0,
                "above_reserve": False,
            },
            phase_num=0,
            phase_name="Founder-Backed Build",
            preflight_ok=False,
        )
        self.assertEqual(report["verdict"], "OWNER_BLOCKED_TREASURY")
        self.assertEqual(report["phase"]["number"], 0)
        self.assertEqual(report["treasury"]["customer_revenue_usd"], 0.0)
        self.assertEqual(report["treasury"]["support_received_usd"], 0.0)
        self.assertEqual(report["treasury"]["owner_capital_usd"], 0.0)

    def test_phase_blocked_automation_requires_phase_four_even_if_cash_is_clear(self):
        report = self._collect(
            treasury={
                "balance_usd": 75.0,
                "reserve_floor_usd": 50.0,
                "runway_usd": 25.0,
                "shortfall_usd": 0.0,
                "above_reserve": True,
            },
            phase_num=2,
            phase_name="Customer-Validated Pilot",
            preflight_ok=False,
        )
        self.assertEqual(report["verdict"], "PHASE_BLOCKED_AUTOMATION")
        self.assertEqual(report["phase"]["name"], "Customer-Validated Pilot")
        self.assertEqual(report["treasury"]["customer_revenue_usd"], 0.0)

    def test_constitution_blocked_preflight_only_after_automation_phase(self):
        report = self._collect(
            treasury={
                "balance_usd": 100.0,
                "reserve_floor_usd": 50.0,
                "runway_usd": 50.0,
                "shortfall_usd": 0.0,
                "above_reserve": True,
            },
            phase_num=4,
            phase_name="Treasury-Cleared Automation",
            preflight_ok=False,
        )
        self.assertEqual(report["verdict"], "CONSTITUTION_BLOCKED_PREFLIGHT")

    def test_service_probe_ok_accepts_terminal_markers(self):
        self.assertTrue(
            readiness._service_probe_ok(
                {
                    "ok": True,
                    "stdout": "agent log\nHEARTBEAT_OK\n",
                    "stderr": "",
                }
            )
        )
        self.assertFalse(
            readiness._service_probe_ok(
                {
                    "ok": True,
                    "stdout": "agent log\nHEARTBEAT_WAITING\n",
                    "stderr": "",
                }
            )
        )

    def test_print_report_includes_normalized_loom_import_metadata(self):
        report = {
            'checked_at': '2026-03-25T00:00:00Z',
            'verdict': 'READY_FOR_CONTROLLED_DELIVERY_CHECK',
            'runtime': {'health_ok': True, 'service_probe_ok': True, 'service_probe_output': '{"running": true}'},
            'treasury': {
                'blocked': False,
                'runway_usd': 25.0,
                'customer_revenue_usd': 0.0,
                'support_received_usd': 0.0,
                'owner_capital_usd': 0.0,
            },
            'phase': {'number': 4, 'name': 'Treasury-Cleared Automation'},
            'preflight': {'ok': True, 'summary': 'PREFLIGHT: OK'},
            'route_cutovers': {
                'intelligence_on_demand_research': {
                    'owner': 'loom',
                    'runtime_source': 'route_override',
                    'fallback_enabled': False,
                    'transcript': 'route=intelligence_on_demand_research | requested=loom | selected=loom | fallback=off | preflight=ok | capability=clawskill.safe-web-research.v0',
                    'loom_preflight': {
                        'ok': True,
                        'errors': [],
                        'normalized_import_metadata': {
                            'supported': True,
                            'skill_slug': 'safe-web-research',
                            'worker_entry': 'workers/python/imported-clawskill-safe-web-research-v0.py',
                        },
                    },
                }
            },
            'brief': {'exists': False, 'path': None, 'date': None},
            'delivery_targets': {'count': 0, 'internal_test_count': 0},
        }

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            readiness.print_report(report)

        output = buffer.getvalue()
        self.assertIn('On-demand research Loom import metadata: OK skill=safe-web-research', output)
        self.assertIn('On-demand research transcript: route=intelligence_on_demand_research', output)


if __name__ == "__main__":
    unittest.main()
