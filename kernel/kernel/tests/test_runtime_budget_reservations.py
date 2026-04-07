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


treasury = _load_module("kernel_treasury_runtime_budget_test", TREASURY_PATH)
capsule = _load_module("kernel_capsule_runtime_budget_test", CAPSULE_PATH)
import authority  # noqa: E402


class RuntimeBudgetReservationTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f"org_runtime_budget_{uuid.uuid4().hex[:8]}"
        self.capsule_dir = ROOT / "capsules" / self.org_id
        capsule.init_capsule(self.org_id)
        ledger_path = pathlib.Path(capsule.capsule_path(self.org_id, "ledger.json"))
        ledger = json.loads(ledger_path.read_text())
        ledger["treasury"]["cash_usd"] = 100.0
        ledger["treasury"]["reserve_floor_usd"] = 10.0
        ledger["treasury"]["burn_rate_30d_usd"] = 30.0
        ledger["agents"] = {
            "atlas": {
                "name": "Atlas",
                "role": "analyst",
                "reputation_units": 80,
                "authority_units": 80,
                "probation": False,
                "zero_authority": False,
                "status": "active",
            }
        }
        ledger_path.write_text(json.dumps(ledger, indent=2))

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def _reserve(self, amount=5.0):
        with mock.patch.object(treasury, "_resolve_budget_agent", return_value={"id": "atlas"}), \
             mock.patch.object(treasury, "_agent_check_budget", return_value=(True, "ok")), \
             mock.patch.object(authority, "check_authority", return_value=(True, "ok")):
            return treasury.reserve_runtime_budget(
                "atlas",
                amount,
                org_id=self.org_id,
                action="research",
                resource="web_search",
                context={"input_hash": "abc123"},
                lease_seconds=60,
                policy_ref="test_runtime_budget",
            )

    def test_reserve_commit_release_lifecycle_updates_summary(self):
        reserved = self._reserve(5.0)
        self.assertTrue(reserved["allowed"])
        reservation_id = reserved["reservation"]["reservation_id"]
        summary = treasury.budget_reservation_summary(self.org_id)
        self.assertEqual(summary["active_reservation_count"], 1)
        self.assertAlmostEqual(summary["active_reserved_usd"], 5.0, places=2)

        committed = treasury.commit_runtime_budget(
            reservation_id,
            4.5,
            org_id=self.org_id,
            note="runtime worker completed",
        )
        self.assertEqual(committed["status"], "committed")
        summary = treasury.budget_reservation_summary(self.org_id)
        self.assertEqual(summary["active_reservation_count"], 0)
        self.assertAlmostEqual(summary["committed_usd"], 4.5, places=2)

        released = self._reserve(3.0)
        released_id = released["reservation"]["reservation_id"]
        result = treasury.release_runtime_budget(
            released_id,
            org_id=self.org_id,
            reason="worker_failed",
        )
        self.assertEqual(result["status"], "released")
        summary = treasury.budget_reservation_summary(self.org_id)
        self.assertAlmostEqual(summary["released_usd"], 3.0, places=2)

    def test_expire_reservations_moves_amount_to_expired(self):
        reserved = self._reserve(2.5)
        reservation_id = reserved["reservation"]["reservation_id"]
        store = treasury._load_budget_reservation_store(self.org_id)
        store["reservations"][reservation_id]["expires_at"] = "2020-01-01T00:00:00Z"
        treasury._save_budget_reservation_store(store, self.org_id)

        treasury.expire_runtime_budget_reservations(self.org_id, "2026-03-23T00:00:00Z")
        reservation = treasury.get_runtime_budget_reservation(reservation_id, self.org_id)
        self.assertEqual(reservation["status"], "expired")
        summary = treasury.budget_reservation_summary(self.org_id)
        self.assertAlmostEqual(summary["expired_usd"], 2.5, places=2)
        snapshot = treasury.treasury_snapshot(self.org_id)
        self.assertIn("runtime_budget", snapshot)
        self.assertEqual(snapshot["runtime_budget"]["expired_reservation_count"], 1)


if __name__ == "__main__":
    unittest.main()
