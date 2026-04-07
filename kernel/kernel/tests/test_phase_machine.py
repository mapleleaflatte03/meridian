#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "phase_machine.py"
SPEC = importlib.util.spec_from_file_location("kernel_phase_machine", MODULE_PATH)
phase_machine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase_machine)


class PhaseMachineTests(unittest.TestCase):
    def test_customer_validated_pilot_does_not_require_support_first(self):
        ledger = {
            "epoch": {"number": 0},
            "treasury": {
                "cash_usd": 1.0,
                "reserve_floor_usd": 50.0,
                "total_revenue_usd": 1.0,
                "support_received_usd": 0.0,
                "owner_capital_contributed_usd": 2.0,
            },
        }
        revenue = {
            "orders": {
                "ord1": {
                    "status": "paid",
                    "client": "client-a",
                    "product": "pilot",
                }
            }
        }
        with mock.patch.object(phase_machine, "_load_ledger", return_value=ledger), \
             mock.patch.object(phase_machine, "_load_revenue", return_value=revenue):
            current, details = phase_machine.current_phase()
        self.assertEqual(current, 2)
        self.assertEqual(details["name"], "Customer-Validated Pilot")

    def test_phase_three_counts_client_field_from_revenue_orders(self):
        ledger = {
            "epoch": {"number": 0},
            "treasury": {
                "cash_usd": 5.0,
                "reserve_floor_usd": 50.0,
                "total_revenue_usd": 5.0,
                "support_received_usd": 0.0,
                "owner_capital_contributed_usd": 2.0,
            },
        }
        revenue = {
            "orders": {
                "ord1": {"status": "paid", "client": "client-a", "product": "pilot-a"},
                "ord2": {"status": "paid", "client": "client-b", "product": "pilot-b"},
                "ord3": {"status": "paid", "client": "client-a", "product": "pilot-c"},
            }
        }
        with mock.patch.object(phase_machine, "_load_ledger", return_value=ledger), \
             mock.patch.object(phase_machine, "_load_revenue", return_value=revenue):
            current, details = phase_machine.current_phase()
        self.assertEqual(current, 3)
        self.assertEqual(details["name"], "Customer-Backed Treasury")


if __name__ == "__main__":
    unittest.main()
