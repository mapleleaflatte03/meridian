#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import shutil
import sys
import unittest
import uuid
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
KERNEL_DIR = ROOT / "kernel"
if str(KERNEL_DIR) not in sys.path:
    sys.path.insert(0, str(KERNEL_DIR))

TREASURY_PATH = KERNEL_DIR / "treasury.py"
CAPSULE_PATH = KERNEL_DIR / "capsule.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


treasury = _load_module("kernel_treasury_stabilization_test", TREASURY_PATH)
capsule = _load_module("kernel_capsule_stabilization_test", CAPSULE_PATH)
import authority  # noqa: E402


class TreasuryStabilizationLaneTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f"org_treasury_stability_{uuid.uuid4().hex[:8]}"
        self.capsule_dir = ROOT / "capsules" / self.org_id
        capsule.init_capsule(self.org_id)
        ledger_path = pathlib.Path(capsule.capsule_path(self.org_id, "ledger.json"))
        ledger = json.loads(ledger_path.read_text())
        ledger["treasury"]["cash_usd"] = 250.0
        ledger["treasury"]["reserve_floor_usd"] = 25.0
        ledger["treasury"]["burn_rate_30d_usd"] = 60.0
        ledger["agents"] = {
            "atlas": {
                "name": "Atlas",
                "role": "analyst",
                "reputation_units": 90,
                "authority_units": 90,
                "probation": False,
                "zero_authority": False,
                "status": "active",
            }
        }
        ledger_path.write_text(json.dumps(ledger, indent=2))

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def _reserve(self, amount):
        with mock.patch.object(treasury, "_resolve_budget_agent", return_value={"id": "atlas"}), \
             mock.patch.object(treasury, "_agent_check_budget", return_value=(True, "ok")), \
             mock.patch.object(authority, "check_authority", return_value=(True, "ok")):
            return treasury.reserve_runtime_budget(
                "atlas",
                amount,
                org_id=self.org_id,
                action="stability_lane",
                resource="runtime.execute",
                context={"lane": "treasury_stabilization"},
                lease_seconds=120,
                policy_ref="treasury_stabilization_lane_v1",
            )

    def test_budget_reservation_lifecycle_stays_consistent_under_mixed_flow(self):
        first = self._reserve(4.0)
        first_id = first["reservation"]["reservation_id"]
        treasury.commit_runtime_budget(first_id, 3.5, org_id=self.org_id, note="lane_commit")

        second = self._reserve(2.0)
        second_id = second["reservation"]["reservation_id"]
        treasury.release_runtime_budget(second_id, org_id=self.org_id, reason="lane_release")

        third = self._reserve(1.0)
        third_id = third["reservation"]["reservation_id"]
        store = treasury._load_budget_reservation_store(self.org_id)
        store["reservations"][third_id]["expires_at"] = "2020-01-01T00:00:00Z"
        treasury._save_budget_reservation_store(store, self.org_id)
        treasury.expire_runtime_budget_reservations(self.org_id, "2026-04-05T00:00:00Z")

        summary = treasury.budget_reservation_summary(self.org_id, agent_id="atlas")
        self.assertEqual(summary["active_reservation_count"], 0)
        self.assertAlmostEqual(summary["committed_usd"], 3.5, places=2)
        self.assertAlmostEqual(summary["released_usd"], 2.0, places=2)
        self.assertAlmostEqual(summary["expired_usd"], 1.0, places=2)
        self.assertGreaterEqual(summary["available_for_reservation_usd"], 0.0)

        snapshot = treasury.treasury_snapshot(self.org_id)
        runtime_budget = snapshot.get("runtime_budget") or {}
        self.assertEqual(runtime_budget.get("active_reservation_count"), 0)
        self.assertAlmostEqual(runtime_budget.get("committed_usd", 0.0), 3.5, places=2)
        self.assertAlmostEqual(runtime_budget.get("released_usd", 0.0), 2.0, places=2)
        self.assertAlmostEqual(runtime_budget.get("expired_usd", 0.0), 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
